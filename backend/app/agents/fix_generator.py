import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from cerebras.cloud.sdk import Cerebras

from app.agents.state import AgentState
from app.config import settings


MAX_PROMPT_CODE_CHARS = 28000
MAX_FILE_SNIPPET_CHARS = 4800
MAX_RETRIEVAL_FILES_IN_PROMPT = 5
MAX_LOCAL_CONTEXT_FILES = 6
MAX_LOCAL_CONTEXT_CHARS = 120000
MAX_EDITS = 4
MAX_LOCAL_FILE_BYTES = 1_500_000
MAX_LOCAL_READ_CHARS = 800_000
LOCAL_WINDOWS_BUILD_BUDGET_SECONDS = 8
OPENROUTER_CONNECT_TIMEOUT_SECONDS = 15
OPENROUTER_READ_TIMEOUT_SECONDS = 60
OPENROUTER_MAX_HTTP_RETRIES = 2
MAX_REANCHOR_FILE_CONTEXT_CHARS = 48000
FIX_GENERATION_MAX_TOKENS = 9000
REANCHOR_MAX_TOKENS = 7200

_cerebras_client: Cerebras | None = None


def _get_cerebras_client() -> Cerebras:
    global _cerebras_client
    if _cerebras_client is None:
        _cerebras_client = Cerebras(api_key=settings.CEREBRAS_API_KEY)
    return _cerebras_client


def _active_llm_label() -> str:
    if settings.CEREBRAS_API_KEY:
        return f"Cerebras ({settings.CEREBRAS_MODEL})"
    if settings.OPENROUTER_API_KEY:
        return f"OpenRouter ({settings.OPENROUTER_MODEL})"
    if settings.GROQ_API_KEY:
        return "Groq (llama-3.3-70b-versatile)"
    return "No LLM configured"


def _chat_completion(prompt: str, temperature: float, max_tokens: int) -> str:
    if settings.CEREBRAS_API_KEY:
        last_exc: Exception | None = None
        for attempt in range(1, OPENROUTER_MAX_HTTP_RETRIES + 1):
            try:
                started = time.time()
                response = _get_cerebras_client().chat.completions.create(
                    model=settings.CEREBRAS_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                    max_completion_tokens=max_tokens,
                )
                content = None
                if response.choices:
                    content = response.choices[0].message.content
                if content is None:
                    raise ValueError("LLM returned empty message content")
                if isinstance(content, list):
                    parts = []
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            parts.append(item.get("text", ""))
                        elif isinstance(item, str):
                            parts.append(item)
                    content = "\n".join(part for part in parts if part)
                content = str(content)
                if not content.strip():
                    raise ValueError("LLM returned blank message content")
                elapsed = round(time.time() - started, 2)
                print(f"   LLM response received in {elapsed}s")
                return content
            except (requests.Timeout, requests.ConnectionError, requests.HTTPError, ValueError) as exc:
                last_exc = exc
                print(f"   LLM call attempt {attempt}/{OPENROUTER_MAX_HTTP_RETRIES} failed: {exc}")
                if attempt < OPENROUTER_MAX_HTTP_RETRIES:
                    time.sleep(1.0)
            except Exception as exc:
                last_exc = exc
                print(f"   LLM call attempt {attempt}/{OPENROUTER_MAX_HTTP_RETRIES} failed: {exc}")
                if attempt < OPENROUTER_MAX_HTTP_RETRIES:
                    time.sleep(1.0)

        raise RuntimeError(f"Cerebras call failed after retries: {last_exc}")

    if settings.OPENROUTER_API_KEY:
        headers = {
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "X-Title": settings.OPENROUTER_APP_NAME,
        }
        if settings.OPENROUTER_HTTP_REFERER:
            headers["HTTP-Referer"] = settings.OPENROUTER_HTTP_REFERER

        payload = {
            "model": settings.OPENROUTER_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        response = requests.post(
            f"{settings.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
            timeout=(OPENROUTER_CONNECT_TIMEOUT_SECONDS, OPENROUTER_READ_TIMEOUT_SECONDS),
        )
        response.raise_for_status()
        body = response.json()
        content = body.get("choices", [{}])[0].get("message", {}).get("content")
        if content is None:
            raise ValueError("LLM returned empty message content")
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif isinstance(item, str):
                    parts.append(item)
            content = "\n".join(part for part in parts if part)
        content = str(content)
        if not content.strip():
            raise ValueError("LLM returned blank message content")
        return content

    if settings.GROQ_API_KEY:
        from groq import Groq

        groq_client = Groq(api_key=settings.GROQ_API_KEY)
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    raise RuntimeError("No LLM key configured. Set CEREBRAS_API_KEY, OPENROUTER_API_KEY, or GROQ_API_KEY.")


def _extract_description(ticket: dict) -> str:
    """
    Jira descriptions may arrive as Atlassian Document Format.
    Extract plain text so prompt formatting stays stable.
    """

    desc = ticket.get("description", "")

    if isinstance(desc, str):
        return desc

    if isinstance(desc, dict):
        texts: List[str] = []

        def _extract(node):
            if isinstance(node, dict):
                if node.get("type") == "text":
                    texts.append(node.get("text", ""))
                for child in node.get("content", []):
                    _extract(child)

        _extract(desc)
        return " ".join(texts)

    return str(desc)


def _escape_unescaped_newlines_in_strings(value: str) -> str:
    out: List[str] = []
    in_string = False
    escape_next = False

    for ch in value:
        if in_string:
            if escape_next:
                out.append(ch)
                escape_next = False
                if ch == "\\":
                    escape_next = True
            elif ch == "\\":
                out.append(ch)
                escape_next = True
            elif ch == '"':
                out.append(ch)
                in_string = False
            elif ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                out.append("\\r")
            else:
                out.append(ch)
        else:
            out.append(ch)
            if ch == '"':
                in_string = True

    return "".join(out)


def _escape_json_string_for_parsing(value: str) -> str:
    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    value = value.replace("\n", "\\n")
    value = value.replace("\r", "\\r")
    value = value.replace("\t", "\\t")
    return value


def _sanitize_json_string_field(raw: str, field_name: str) -> str:
    pattern = rf'"{field_name}"\s*:\s*"(.*?)"(?=\s*,\s*"|\s*\}})'
    match = re.search(pattern, raw, flags=re.DOTALL)
    if not match:
        return raw

    field_raw = match.group(1)
    field_escaped = _escape_json_string_for_parsing(field_raw)
    return raw[: match.start(1)] + field_escaped + raw[match.end(1) :]


def _parse_llm_json(raw: str) -> dict:
    raw = raw.strip()

    try:
        return json.loads(raw, strict=False)
    except Exception:
        pass

    raw = _escape_unescaped_newlines_in_strings(raw)

    for field_name in ["original_code", "fixed_code", "target", "replacement"]:
        raw = _sanitize_json_string_field(raw, field_name)

    try:
        return json.loads(raw, strict=False)
    except Exception:
        pass

    start = raw.find("{")
    if start != -1:
        depth = 0
        for idx in range(start, len(raw)):
            if raw[idx] == "{":
                depth += 1
            elif raw[idx] == "}":
                depth -= 1
                if depth == 0:
                    candidate = raw[start : idx + 1]
                    try:
                        return json.loads(candidate, strict=False)
                    except Exception:
                        try:
                            return json.loads(candidate.replace("'", '"'), strict=False)
                        except Exception:
                            break

    import ast

    normalized = raw
    normalized = re.sub(r"\bNone\b", "null", normalized)
    normalized = re.sub(r"\bTrue\b", "true", normalized)
    normalized = re.sub(r"\bFalse\b", "false", normalized)

    try:
        return json.loads(normalized, strict=False)
    except Exception:
        try:
            return ast.literal_eval(raw)
        except Exception:
            excerpt = raw if len(raw) <= 1000 else raw[:1000] + "..."
            raise ValueError(
                "Failed to parse LLM JSON response. "
                f"Raw output excerpt:\n{excerpt}"
            )


def _sanitize_prompt_text(value: str) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value or "")


def _decode_multiline_field(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    decoded = value
    if "\\n" in decoded and "\n" not in decoded:
        try:
            decoded = bytes(decoded, "utf-8").decode("unicode_escape")
        except Exception:
            pass
    return decoded


def _normalize_edit_payload(edit: dict) -> dict:
    if not isinstance(edit, dict):
        return {}

    operation = str(edit.get("operation") or "replace").strip().lower()
    normalized = {
        "file": str(edit.get("file") or "").strip().replace("\\", "/"),
        "operation": operation,
        "target": _decode_multiline_field(edit.get("target")),
        "replacement": _decode_multiline_field(edit.get("replacement")),
    }
    if operation == "create_file":
        normalized["target"] = ""
    return normalized


def _normalize_fix_payload(fix_data: dict, prior_confidence: float | None = None) -> dict:
    if not isinstance(fix_data, dict):
        raise ValueError("Fix payload is not a JSON object")

    raw_edits = fix_data.get("edits")
    if isinstance(raw_edits, list) and raw_edits:
        edits = [_normalize_edit_payload(item) for item in raw_edits[:MAX_EDITS]]
    else:
        edits = [
            {
                "file": str(fix_data.get("file") or "").strip().replace("\\", "/"),
                "operation": "replace",
                "target": _decode_multiline_field(fix_data.get("original_code")),
                "replacement": _decode_multiline_field(fix_data.get("fixed_code")),
            }
        ]

    normalized_edits = []
    for edit in edits:
        if not edit.get("file"):
            continue
        if edit.get("operation") not in {"replace", "insert_after", "insert_before", "create_file"}:
            continue
        if edit["operation"] != "create_file" and not edit.get("target", "").strip():
            continue
        if not edit.get("replacement", "").strip():
            continue
        normalized_edits.append(edit)

    if not normalized_edits:
        raise ValueError("No valid edits returned by LLM")

    confidence = fix_data.get("confidence")
    if confidence is None:
        confidence = float(prior_confidence) * 100 if prior_confidence is not None else 0.0
    else:
        try:
            confidence = float(confidence)
        except Exception:
            confidence = 0.0

    if 0.0 <= confidence <= 1.0:
        confidence *= 100

    normalized = {
        "edits": normalized_edits,
        "reason": str(fix_data.get("reason") or "").strip(),
        "confidence": round(confidence, 2),
    }
    normalized["primary_file"] = normalized_edits[0]["file"]
    normalized["file"] = normalized["primary_file"]
    normalized["original_code"] = normalized_edits[0].get("target", "")
    normalized["fixed_code"] = normalized_edits[0].get("replacement", "")
    return normalized


def _format_retrieval_context(retrieval_context: Optional[Dict[str, Any]]) -> str:
    if not retrieval_context:
        return ""

    sections: List[str] = []

    query = retrieval_context.get("query")
    if query:
        sections.append(f"Retrieval query: {query}")

    repo_state = retrieval_context.get("repo_state") or {}
    if repo_state:
        sections.append(
            "\n".join(
                [
                    "Repo state:",
                    f"- branch={repo_state.get('branch') or 'unknown'}",
                    f"- commit={repo_state.get('commit_sha') or 'unknown'}",
                    f"- requested_commit={repo_state.get('requested_commit_sha') or 'n/a'}",
                    f"- commit_aligned={repo_state.get('commit_aligned')}",
                    f"- dirty_worktree={repo_state.get('dirty')}",
                ]
            )
        )

    repo_profile = retrieval_context.get("repo_profile") or {}
    if repo_profile:
        primary_service = repo_profile.get("primary_service") or {}
        sections.append(
            "\n".join(
                [
                    "Repo profile:",
                    f"- languages={repo_profile.get('languages') or []}",
                    f"- frameworks={repo_profile.get('frameworks') or []}",
                    f"- primary_service={primary_service}",
                    f"- docker_compose={repo_profile.get('has_docker_compose')}",
                ]
            )
        )

    validation_plan = retrieval_context.get("validation_plan") or retrieval_context.get("validation_context") or {}
    if validation_plan:
        sections.append(
            "\n".join(
                [
                    "Validation path:",
                    f"- source={validation_plan.get('source')}",
                    f"- execution_mode={validation_plan.get('execution_mode')}",
                    f"- service={validation_plan.get('service')}",
                    f"- build_command={validation_plan.get('build_command')}",
                    f"- selected_tests={validation_plan.get('selected_test_paths') or []}",
                ]
            )
        )

    remote_signals = retrieval_context.get("remote_signals") or {}
    if remote_signals:
        sections.append(
            "\n".join(
                [
                    "Discovery signals:",
                    f"- mcp_candidate_paths={remote_signals.get('mcp_candidate_paths') or []}",
                    f"- history_related_paths={remote_signals.get('history_related_paths') or []}",
                ]
            )
        )

    seed_files = retrieval_context.get("seed_files") or []
    if seed_files:
        lines = ["Seed files from discovery:"]
        for item in seed_files[:5]:
            lines.append(
                f"- {item.get('path')} | similarity={item.get('similarity')} | symbol={item.get('symbol_name') or 'n/a'}"
            )
        sections.append("\n".join(lines))

    symbol_graph_summary = retrieval_context.get("symbol_graph_summary") or {}
    if symbol_graph_summary:
        sections.append(
            "\n".join(
                [
                    "Symbol graph summary:",
                    f"- routes={len(symbol_graph_summary.get('route_files') or [])}",
                    f"- services={len(symbol_graph_summary.get('service_files') or [])}",
                    f"- models={len(symbol_graph_summary.get('model_files') or [])}",
                    f"- migrations={len(symbol_graph_summary.get('migration_files') or [])}",
                    f"- tests={len(symbol_graph_summary.get('test_files') or [])}",
                ]
            )
        )

    ranked_files = retrieval_context.get("ranked_files") or []
    if ranked_files:
        lines = ["Top ranked files:"]
        for idx, item in enumerate(ranked_files[:MAX_RETRIEVAL_FILES_IN_PROMPT], 1):
            reasons = ", ".join(item.get("relation_reasons", [])) or "ranked"
            lines.append(
                "\n".join(
                    [
                        f"{idx}. {item.get('path')}",
                        f"   score={item.get('score', item.get('similarity', 0))} similarity={item.get('similarity', 0)}",
                        f"   symbol={item.get('symbol_name') or 'n/a'} lines={item.get('start_line')}->{item.get('end_line')}",
                        f"   reasons={reasons}",
                        f"   preview:\n{item.get('content_preview', '')[:180]}",
                    ]
                )
            )
        sections.append("\n".join(lines))

    graph_edges = retrieval_context.get("graph_edges") or []
    if graph_edges:
        lines = ["Relevant graph relations:"]
        for edge in graph_edges[:8]:
            lines.append(
                f"- {edge.get('source_key')} --{edge.get('edge_type')}--> {edge.get('target_key')}"
            )
        sections.append("\n".join(lines))

    return _sanitize_prompt_text("\n\n".join(sections))


def _compact_code_snippets(code_snippets: str, retrieval_context: Optional[Dict[str, Any]]) -> str:
    """
    Keep prompt context focused: prioritize top-ranked files and cap total size.
    """
    if not code_snippets:
        return ""

    if not retrieval_context:
        return code_snippets[:MAX_PROMPT_CODE_CHARS]

    ranked_files = retrieval_context.get("ranked_files") or []
    selected_blocks: List[str] = []
    for item in ranked_files[:MAX_RETRIEVAL_FILES_IN_PROMPT]:
        path = item.get("path")
        focused = str(item.get("focused_content") or item.get("content_preview") or "").strip()
        if not path or not focused:
            continue
        selected_blocks.append(
            "\n".join(
                [
                    f"# File: {path}",
                    focused[:MAX_FILE_SNIPPET_CHARS],
                ]
            )
        )

    compact = "\n\n---\n\n".join(selected_blocks)
    if not compact.strip():
        compact = code_snippets
    return compact[:MAX_PROMPT_CODE_CHARS]


def _build_local_file_context(
    retrieval_context: Optional[Dict[str, Any]],
    analysis_terms: Optional[List[str]],
    repo_root: Optional[Path],
) -> str:
    if not retrieval_context:
        return ""

    grounded_files = retrieval_context.get("grounded_files") or retrieval_context.get("ranked_files") or []
    if not grounded_files:
        return ""

    _ = analysis_terms
    blocks: List[str] = []
    started = time.time()

    print("   Building full local file context...")

    for item in grounded_files[:MAX_LOCAL_CONTEXT_FILES]:
        if (time.time() - started) > LOCAL_WINDOWS_BUILD_BUDGET_SECONDS:
            print("   Local context build budget exceeded; continuing without more files")
            break

        rel_path = str(item.get("path") or "").replace("\\", "/").strip()
        content = str(item.get("content") or "")
        if not rel_path or not content.strip():
            continue

        blocks.append(
            "\n".join(
                [
                    f"# Full File: {rel_path}",
                    content[:MAX_LOCAL_READ_CHARS],
                ]
            )
        )

    merged = "\n\n---\n\n".join(blocks)
    print(f"   Local full files included: {len(blocks)}")
    return merged[:MAX_LOCAL_CONTEXT_CHARS]


def _build_fix_prompt(
    ticket: dict,
    description: str,
    code_snippets: str,
    retrieval_context: Optional[Dict[str, Any]],
    repo_root: Optional[Path],
    retry_feedback: Optional[str] = None,
    analysis_terms: Optional[List[str]] = None,
) -> str:
    retrieval_summary = _format_retrieval_context(retrieval_context)
    compact_code = _compact_code_snippets(code_snippets, retrieval_context)
    local_file_context = _build_local_file_context(retrieval_context, analysis_terms, repo_root)
    ranked_files = retrieval_context.get("ranked_files", [])[:6] if retrieval_context else []
    likely_file_list = ", ".join(
        item.get("path", "") for item in ranked_files if item.get("path")
    ) or "not available"

    prompt_parts = [
        "You are an expert software engineer fixing bugs.",
        "",
        "Bug ticket:",
        f"Key: {ticket.get('jira_key', 'Unknown')}",
        f"Summary: {ticket.get('summary', 'No summary')}",
        f"Description: {description}",
        "",
    ]

    if retrieval_summary:
        prompt_parts.extend(
            [
            "Structured retrieval context:",
            retrieval_summary,
            "",
            f"Most likely grounded files to edit: {likely_file_list}",
            "",
        ]
    )

    if retry_feedback:
        prompt_parts.extend(
            [
                "Previous failed attempt diagnostics (must address these issues):",
                retry_feedback,
                "",
            ]
        )

    if local_file_context:
        prompt_parts.extend(
            [
                "High-fidelity local full-file context (authoritative source for exact patching):",
                local_file_context,
                "",
            ]
        )

    prompt_parts.extend(
        [
            "Relevant code snippets (focused subset):",
            compact_code,
            "",
            "Generate a minimal, compilable fix for this bug. Return ONLY a JSON object with these exact fields:",
            '- "edits": an array with 1 to 4 edit objects',
            '  Each edit object must contain:',
            '  - "file": exact repo-relative file path',
            '  - "operation": one of ["replace", "insert_after", "insert_before", "create_file"]',
            '  - "target": exact existing code snippet for replace/insert operations; empty string only for create_file',
            '  - "replacement": corrected code/content to write',
            '- "reason": brief explanation of why this fixes the issue',
            '- "confidence": a number 0.0-100.0 representing your confidence in this fix (higher is better)',
            "",
            "Treat discovery hints and MCP suggestions as discovery only. Use the authoritative local full-file context as the final source of truth.",
            "Use the structured retrieval context to follow the implementation path and validation path together, including selected tests when they are relevant.",
            "For replace, insert_after, and insert_before operations, copy target exactly from the authoritative local full-file context, including indentation and spacing.",
            "Focus on minimal, targeted fixes. If the fix requires adding a dependency, specify the exact version if known.",
            "Include multi-file edits only when strictly necessary to make the incident pass (e.g., coupled source+test or source+migration changes).",
            "Do not include cosmetic, formatting-only, or refactor-only edits.",
            "Preserve the original file's multi-line formatting exactly. Do NOT collapse multi-line expressions into a single line.",
            "If the fix spans multiple files, include all required edits, including tests or migrations when needed.",
            "If you add a database field, column, or schema change, include the required migration edit in the same response.",
            "Do not include placeholder files, guessed paths, or commentary.",
            "Respond with ONLY valid JSON. No markdown, no explanation.",
        ]
    )

    return _sanitize_prompt_text("\n".join(prompt_parts))


def _format_candidate_files(retry_context: Optional[Dict[str, Any]]) -> str:
    if not retry_context:
        return ""

    blocks: List[str] = []
    for item in (retry_context.get("candidate_files") or [])[:4]:
        path = str(item.get("path") or "").strip()
        content = str(item.get("content") or "")
        if not path or not content:
            continue
        blocks.append(
            "\n".join(
                [
                    f"# Candidate File: {path}",
                    content[:MAX_REANCHOR_FILE_CONTEXT_CHARS],
                ]
            )
        )
    return "\n\n---\n\n".join(blocks)


def _build_reanchor_prompt(
    ticket: dict,
    description: str,
    retry_context: Dict[str, Any],
) -> str:
    failed_edit = retry_context.get("failed_edit") or {}
    candidate_file_context = _format_candidate_files(retry_context)
    anchor_diagnostics = retry_context.get("anchor_diagnostics") or []
    validation_context = retry_context.get("validation_context") or {}
    validation_plan = retry_context.get("validation_plan") or {}
    repo_profile = retry_context.get("repo_profile") or {}

    prompt_parts = [
        "You are re-anchoring a previously valid bug-fix idea against the exact local source code.",
        "",
        "Bug ticket:",
        f"Key: {ticket.get('jira_key', 'Unknown')}",
        f"Summary: {ticket.get('summary', 'No summary')}",
        f"Description: {description}",
        "",
        "Previous patch intent:",
        f"Reason: {retry_context.get('previous_fix_reason', '')}",
        f"Confidence: {retry_context.get('previous_fix_confidence', '')}",
        "",
        "Failed edit to re-anchor:",
        f"- file: {failed_edit.get('requested_file') or failed_edit.get('resolved_file')}",
        f"- resolved_file: {failed_edit.get('resolved_file')}",
        f"- operation: {failed_edit.get('operation')}",
        f"- failure_reason: {failed_edit.get('failure_reason')}",
        "Exact failed target snippet:",
        str(failed_edit.get("target") or ""),
        "",
    ]

    if anchor_diagnostics:
        prompt_parts.extend(
            [
                "Anchor diagnostics from the failed attempt:",
                json.dumps(anchor_diagnostics[:4], ensure_ascii=True),
                "",
            ]
        )

    if validation_context:
        prompt_parts.extend(
            [
                "Validation context:",
                json.dumps(validation_context, ensure_ascii=True),
                "",
            ]
        )

    if validation_plan:
        prompt_parts.extend(
            [
                "Validation plan:",
                json.dumps(validation_plan, ensure_ascii=True),
                "",
            ]
        )

    if repo_profile:
        prompt_parts.extend(
            [
                "Repo profile:",
                json.dumps(repo_profile, ensure_ascii=True),
                "",
            ]
        )

    if candidate_file_context:
        prompt_parts.extend(
            [
                "Authoritative candidate file contents:",
                candidate_file_context,
                "",
            ]
        )

    prompt_parts.extend(
        [
            "Task:",
            "Rewrite the edit plan so every non-create edit target appears exactly in the candidate file content above.",
            "Preserve the previous fix intent. Do not invent schema changes, files, or code paths not present in the candidate files unless create_file is absolutely required.",
            "Prefer editing the existing resolved file if possible, but include selected tests if the validation context makes them necessary.",
            "Return ONLY a JSON object with these exact fields:",
            '- "edits": an array with 1 to 4 edit objects',
            '  Each edit object must contain:',
            '  - "file": exact repo-relative file path',
            '  - "operation": one of ["replace", "insert_after", "insert_before", "create_file"]',
            '  - "target": exact existing code snippet for replace/insert operations; empty string only for create_file',
            '  - "replacement": corrected code/content to write',
            '- "reason": brief explanation of why this re-anchored patch fixes the issue',
            '- "confidence": a number 0.0-100.0 representing your confidence in this re-anchored patch',
            "Respond with ONLY valid JSON. No markdown, no explanation.",
        ]
    )

    return _sanitize_prompt_text("\n".join(prompt_parts))


def generate_fix(
    ticket: dict,
    code_snippets: str,
    prior_confidence: float | None = None,
    retrieval_context: Optional[Dict[str, Any]] = None,
    repo_path: str | None = None,
    retry_feedback: Optional[str] = None,
    fix_attempt: int = 1,
    analysis_terms: Optional[List[str]] = None,
) -> dict:
    """
    Generate a minimal fix for a bug ticket using retrieved code snippets and
    optional structured retrieval context.
    """

    prep_started = time.time()
    description = _extract_description(ticket)
    code_snippets = _sanitize_prompt_text(code_snippets)
    prompt = _build_fix_prompt(
        ticket=ticket,
        description=description,
        code_snippets=code_snippets,
        retrieval_context=retrieval_context,
        repo_root=Path(repo_path).resolve() if repo_path else None,
        retry_feedback=retry_feedback,
        analysis_terms=analysis_terms,
    )
    print(f"   Prompt prepared in {round(time.time() - prep_started, 2)}s")

    generation_temperature = 0.08
    generation_max_tokens = FIX_GENERATION_MAX_TOKENS
    max_generation_attempts = max(1, int(settings.LLM_MAX_GENERATION_RETRIES or 1))
    last_error: Exception | None = None

    for generation_attempt in range(1, max_generation_attempts + 1):
        try:
            print(
                "   Calling LLM "
                f"(attempt={generation_attempt}/{max_generation_attempts}, "
                f"temp={generation_temperature}, max_tokens={generation_max_tokens}, retries={OPENROUTER_MAX_HTTP_RETRIES})"
            )
            raw = _chat_completion(
                prompt,
                temperature=generation_temperature,
                max_tokens=generation_max_tokens,
            ).strip()
            raw = re.sub(r"```json|```", "", raw).strip()
            raw = raw.replace("\t", "    ")
            raw = _sanitize_prompt_text(raw)

            if not raw:
                raise ValueError("LLM returned blank response")

            fix_data = _parse_llm_json(raw)
            normalized = _normalize_fix_payload(fix_data, prior_confidence)
            if not (normalized.get("edits") or []):
                raise ValueError("LLM returned empty edit list")
            return normalized
        except Exception as exc:
            last_error = exc
            print(f"   LLM generation attempt {generation_attempt} failed: {exc}")

    print(f"Fix generation failed after retries: {last_error}")
    return {
        "file": "unknown",
        "primary_file": "unknown",
        "edits": [],
        "fixed_code": "# Fix generation failed",
        "reason": f"Error generating fix: {str(last_error)}",
        "confidence": 0.0,
    }


def reanchor_fix(
    ticket: dict,
    retry_context: Dict[str, Any],
    prior_confidence: float | None = None,
    fix_attempt: int = 1,
) -> dict:
    prep_started = time.time()
    description = _extract_description(ticket)
    prompt = _build_reanchor_prompt(ticket=ticket, description=description, retry_context=retry_context)
    print(f"   Re-anchor prompt prepared in {round(time.time() - prep_started, 2)}s")

    generation_temperature = 0.04
    generation_max_tokens = REANCHOR_MAX_TOKENS
    max_generation_attempts = max(1, int(settings.LLM_MAX_GENERATION_RETRIES or 1))
    last_error: Exception | None = None

    for generation_attempt in range(1, max_generation_attempts + 1):
        try:
            print(
                "   Calling LLM for re-anchor "
                f"(attempt={generation_attempt}/{max_generation_attempts}, "
                f"temp={generation_temperature}, max_tokens={generation_max_tokens}, retries={OPENROUTER_MAX_HTTP_RETRIES})"
            )
            raw = _chat_completion(
                prompt,
                temperature=generation_temperature,
                max_tokens=generation_max_tokens,
            ).strip()
            raw = re.sub(r"```json|```", "", raw).strip()
            raw = raw.replace("\t", "    ")
            raw = _sanitize_prompt_text(raw)

            if not raw:
                raise ValueError("LLM returned blank response")

            fix_data = _parse_llm_json(raw)
            normalized = _normalize_fix_payload(fix_data, prior_confidence)
            if not (normalized.get("edits") or []):
                raise ValueError("LLM returned empty edit list")
            return normalized
        except Exception as exc:
            last_error = exc
            print(f"   LLM re-anchor attempt {generation_attempt} failed: {exc}")

    print(f"Re-anchor generation failed after retries: {last_error}")
    return {
        "file": "unknown",
        "primary_file": "unknown",
        "edits": [],
        "fixed_code": "# Re-anchor generation failed",
        "reason": f"Error re-anchoring fix: {str(last_error)}",
        "confidence": 0.0,
    }


def _selected_file_retry_context(fix: dict, repo_path: str | None) -> Optional[Dict[str, Any]]:
    repo_root = Path(repo_path).resolve() if repo_path else None
    if not repo_root or not repo_root.exists():
        return None

    candidate_files = []
    seen = set()
    edits = fix.get("edits") or []
    for edit in edits[:MAX_EDITS]:
        rel_path = str(edit.get("file") or "").strip().replace("\\", "/")
        if not rel_path or rel_path in seen:
            continue
        seen.add(rel_path)
        candidate = (repo_root / rel_path).resolve()
        if not str(candidate).startswith(str(repo_root)) or not candidate.exists() or not candidate.is_file():
            continue
        try:
            content = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        candidate_files.append(
            {
                "path": rel_path,
                "content": content[:MAX_REANCHOR_FILE_CONTEXT_CHARS],
            }
        )

    if not candidate_files:
        return None

    first_edit = edits[0] if edits else {}
    return {
        "mode": "selected_file_refine",
        "candidate_files": candidate_files,
        "failed_edit": {
            "requested_file": first_edit.get("file"),
            "resolved_file": first_edit.get("file"),
            "operation": first_edit.get("operation"),
            "target": first_edit.get("target"),
        },
        "previous_fix_reason": fix.get("reason"),
        "previous_fix_confidence": fix.get("confidence"),
        "anchor_diagnostics": [],
    }


def fix_generator_node(state: AgentState) -> AgentState:
    """
    LangGraph node: Generate a fix for the analyzed bug.
    Prefers local authoritative retrieval context and falls back to retrieved snippets.
    """

    ticket = state.get("ticket", {})
    retrieval_context = state.get("retrieval_context")
    retrieved_code = state.get("retrieved_code", "")
    retry_feedback = state.get("retry_feedback")
    retry_context = state.get("retry_context")
    fix_attempt = int(state.get("fix_attempt", 1) or 1)
    repo_path = state.get("repo_path") or settings.TARGET_REPO_PATH
    analysis_terms = []
    analysis_terms.extend([str(k) for k in (state.get("keywords") or []) if k])
    if state.get("bug_type"):
        analysis_terms.append(str(state.get("bug_type")))
    if state.get("root_cause_hint"):
        analysis_terms.append(str(state.get("root_cause_hint")))

    if retrieval_context and retrieval_context.get("context_text"):
        retrieved_code = retrieval_context["context_text"]

    if not retrieved_code:
        print("No code retrieved for fix generation")
        return {
            "fix": None,
            "status": "fix_failed",
            "error": "No relevant code found to generate fix",
        }

    print("\nGenerating fix...")
    print(f"[LLM] Provider: {_active_llm_label()}")
    print(f"   Ticket: {ticket.get('jira_key', 'Unknown')}")
    print(f"   Attempt: {fix_attempt}")
    print(f"   Bug Type: {state.get('bug_type', 'Unknown')}")
    if retrieval_context:
        ranked_files = retrieval_context.get("ranked_files", [])
        print(f"   Retrieval candidates: {len(ranked_files)}")
        if ranked_files:
            print(f"   Top file candidate: {ranked_files[0].get('path')}")
    if retry_feedback:
        print("   Retry feedback detected; including prior errors in prompt")

    try:
        if retry_context and retry_context.get("mode") == "reanchor":
            print("   Re-anchor mode detected; grounding against failed edit candidates")
            fix = reanchor_fix(
                ticket=ticket,
                retry_context=retry_context,
                prior_confidence=state.get("confidence"),
                fix_attempt=fix_attempt,
            )
        else:
            fix = generate_fix(
                ticket=ticket,
                code_snippets=retrieved_code,
                prior_confidence=state.get("confidence"),
                retrieval_context=retrieval_context,
                repo_path=repo_path,
                retry_feedback=retry_feedback,
                fix_attempt=fix_attempt,
                analysis_terms=analysis_terms,
            )

            selected_file_context = _selected_file_retry_context(fix, repo_path)
            if selected_file_context:
                print("   Refining against selected file contents...")
                refined_fix = reanchor_fix(
                    ticket=ticket,
                    retry_context=selected_file_context,
                    prior_confidence=fix.get("confidence"),
                    fix_attempt=fix_attempt,
                )
                if (refined_fix.get("edits") or []) and float(refined_fix.get("confidence", 0) or 0) > 0:
                    fix = refined_fix

        confidence = float(fix.get("confidence", 0) or 0)
        edits = fix.get("edits") or []
        primary_file = str(fix.get("primary_file", "")).strip().lower()
        if primary_file in {"", "unknown", "n/a", "none", "null"} or not edits or confidence <= 0:
            error_msg = (
                "Invalid fix payload generated "
                f"(file={fix.get('primary_file')}, confidence={fix.get('confidence')}, edits={len(edits)})"
            )
            print(f"Fix generation failed: {error_msg}")
            return {
                "fix": fix,
                "status": "fix_failed",
                "error": error_msg,
            }

        print("Fix generated:")
        print(f"   Primary File: {fix['primary_file']}")
        print(f"   Edits: {len(edits)}")
        print(f"   Confidence: {fix.get('confidence', 'N/A')}%")
        print(f"   Reason: {fix['reason']}")

        return {
            "fix": fix,
            "status": "fix_generated",
            "error": None,
        }

    except Exception as exc:
        print(f"Fix generation failed: {exc}")
        return {
            "fix": None,
            "status": "fix_failed",
            "error": f"Fix generation error: {str(exc)}",
        }
