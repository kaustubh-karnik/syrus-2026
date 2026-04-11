import ast
import difflib
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.agents.state import AgentState
from app.config import settings
from app.utils.safety_checker import SafetyChecker


CONFIDENCE_THRESHOLD = 80


def _effective_confidence_threshold(fix_attempt: int) -> float:
    return float(max(60, CONFIDENCE_THRESHOLD - max(0, fix_attempt - 1) * 10))


def _clean_generated_code(text: str) -> str:
    text = str(text or "").replace("\r\n", "\n")
    text = re.sub(r"^\s*```[\w]*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text


def _normalize_path(value: str) -> str:
    return str(value or "").strip().replace("\\", "/")


def _normalize_lines(text: str) -> str:
    return "\n".join(line.rstrip() for line in str(text or "").splitlines()).strip()


def _normalize_for_compare(text: str) -> str:
    return _normalize_lines(text)


def _line_offsets(lines: list[str]) -> list[int]:
    offsets: list[int] = []
    total = 0
    for line in lines:
        offsets.append(total)
        total += len(line)
    return offsets


def _safe_rel_path(rel_path: str) -> bool:
    if not rel_path or rel_path.startswith("/") or rel_path.startswith("../"):
        return False
    parts = Path(rel_path).parts
    return ".." not in parts


def _resolve_target_file(
    file_ref: str,
    retrieval_context: Optional[dict],
    repo_root: Path,
    *,
    allow_create: bool = False,
) -> tuple[Path, str, str]:
    normalized = _normalize_path(file_ref)
    if not _safe_rel_path(normalized):
        raise FileNotFoundError(f"Unsafe or invalid file path: {file_ref}")

    direct_path = (repo_root / normalized).resolve()
    if str(direct_path).startswith(str(repo_root.resolve())) and direct_path.exists():
        return direct_path, normalized, "exact_repo_relative_path"

    if retrieval_context:
        ranked_files = retrieval_context.get("grounded_files") or retrieval_context.get("ranked_files", [])
    else:
        ranked_files = []
    ranked_paths = [_normalize_path(item.get("path")) for item in ranked_files if item.get("path")]

    if normalized in ranked_paths:
        ranked_target = repo_root / normalized
        if ranked_target.exists():
            return ranked_target, normalized, "exact_ranked_path"

    basename = Path(normalized).name.lower()
    basename_matches = [path for path in ranked_paths if Path(path).name.lower() == basename]
    if len(basename_matches) == 1:
        ranked_target = repo_root / basename_matches[0]
        if ranked_target.exists():
            return ranked_target, basename_matches[0], "unique_ranked_basename"
    if len(basename_matches) > 1:
        raise FileNotFoundError(f"Ambiguous basename for file path: {file_ref}")

    if allow_create and normalized:
        return direct_path, normalized, "create_file_path"

    raise FileNotFoundError(f"File not found in repo: {file_ref}")


def _find_unique_block(file_content: str, target: str) -> tuple[bool, str, tuple[int, int] | None, str]:
    target = str(target or "")
    if not target.strip():
        return False, "", None, "missing_target"

    exact_matches = [match.start() for match in re.finditer(re.escape(target), file_content)]
    if len(exact_matches) == 1:
        start = exact_matches[0]
        return True, target, (start, start + len(target)), "exact_text_match"
    if len(exact_matches) > 1:
        return False, "", None, "multiple_exact_matches"

    file_lines = file_content.splitlines(keepends=True)
    target_lines = target.splitlines()
    if not target_lines:
        return False, "", None, "empty_target_lines"

    normalized_target = _normalize_lines(target)
    offsets = _line_offsets(file_lines)
    window_size = len(target_lines)
    line_matches: list[tuple[int, int]] = []

    for index in range(0, max(0, len(file_lines) - window_size + 1)):
        window_text = "".join(file_lines[index : index + window_size])
        if _normalize_lines(window_text) == normalized_target:
            line_matches.append((index, index + window_size))

    if len(line_matches) == 1:
        start_line, end_line = line_matches[0]
        start_offset = offsets[start_line]
        end_offset = offsets[end_line] if end_line < len(offsets) else len(file_content)
        original_block = "".join(file_lines[start_line:end_line])
        return True, original_block, (start_offset, end_offset), "normalized_line_match"
    if len(line_matches) > 1:
        return False, "", None, "multiple_normalized_matches"

    return False, "", None, "target_not_found"


def _replace_at_span(content: str, span: tuple[int, int], replacement: str) -> str:
    start, end = span
    return content[:start] + replacement + content[end:]


def _apply_edit_to_content(file_content: str, edit: dict) -> tuple[str, dict]:
    operation = edit["operation"]
    target = edit.get("target", "")
    replacement = edit.get("replacement", "")

    if operation == "create_file":
        return replacement if replacement.endswith("\n") else replacement + "\n", {
            "matched": True,
            "strategy": "create_file",
            "matched_text": "",
        }

    matched, matched_text, span, strategy = _find_unique_block(file_content, target)
    if not matched or span is None:
        raise ValueError(strategy)

    if operation == "replace":
        updated = _replace_at_span(file_content, span, replacement)
    elif operation == "insert_after":
        insert_text = replacement
        if insert_text and not insert_text.startswith("\n"):
            insert_text = "\n" + insert_text
        if insert_text and not insert_text.endswith("\n"):
            insert_text = insert_text + "\n"
        updated = file_content[: span[1]] + insert_text + file_content[span[1] :]
    elif operation == "insert_before":
        insert_text = replacement
        if insert_text and not insert_text.endswith("\n"):
            insert_text = insert_text + "\n"
        if insert_text and not insert_text.startswith("\n"):
            insert_text = "\n" + insert_text
        updated = file_content[: span[0]] + insert_text + file_content[span[0] :]
    else:
        raise ValueError(f"Unsupported edit operation: {operation}")

    return updated, {
        "matched": True,
        "strategy": strategy,
        "matched_text": matched_text,
    }


def _save_unified_diff(
    repo_root: Path,
    original_content: str,
    patched_content: str,
    rel_file_path: str,
    ticket_key: str,
) -> str:
    backups_dir = repo_root / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    safe_path = rel_file_path.replace("/", "_").replace("\\", "_")
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    diff_path = backups_dir / f"{ticket_key}_{safe_path}_{timestamp}.diff"
    diff_lines = difflib.unified_diff(
        original_content.splitlines(keepends=True),
        patched_content.splitlines(keepends=True),
        fromfile=f"a/{rel_file_path}",
        tofile=f"b/{rel_file_path}",
        lineterm="",
    )
    diff_path.write_text("\n".join(diff_lines), encoding="utf-8")
    return str(diff_path)


def _check_python_syntax(content: str, file_path: str) -> tuple[bool, Optional[str]]:
    if not file_path.endswith(".py"):
        return True, None
    try:
        ast.parse(content)
        return True, None
    except SyntaxError as exc:
        return False, f"SyntaxError after patch: {exc}"


def _looks_like_python_import_snippet(text: str) -> bool:
    snippet = str(text or "").strip()
    if not snippet:
        return False
    lines = [line.strip() for line in snippet.splitlines() if line.strip()]
    if not lines:
        return False
    return all(line.startswith("import ") or line.startswith("from ") for line in lines)


def _apply_python_import_fallback(file_content: str, import_snippet: str) -> tuple[str, bool]:
    if not _looks_like_python_import_snippet(import_snippet):
        return file_content, False

    lines = file_content.splitlines(keepends=True)
    if not lines:
        import_block = import_snippet.strip() + "\n\n"
        return import_block, True

    snippet_lines = [line.strip() for line in import_snippet.splitlines() if line.strip()]
    existing = {line.strip() for line in lines}
    missing_lines = [line for line in snippet_lines if line not in existing]
    if not missing_lines:
        return file_content, True

    insert_at = 0
    if lines and lines[0].startswith("#!"):
        insert_at = 1
    if insert_at < len(lines) and lines[insert_at].lstrip().startswith(("'''", '"""')):
        quote = "'''" if lines[insert_at].lstrip().startswith("'''") else '"""'
        insert_at += 1
        while insert_at < len(lines):
            if quote in lines[insert_at]:
                insert_at += 1
                break
            insert_at += 1

    while insert_at < len(lines):
        stripped = lines[insert_at].strip()
        if not stripped:
            insert_at += 1
            continue
        if stripped.startswith("import ") or stripped.startswith("from "):
            insert_at += 1
            continue
        break

    prefix = "".join(lines[:insert_at])
    suffix = "".join(lines[insert_at:])
    insertion = "\n".join(missing_lines) + "\n"
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    if suffix and not suffix.startswith("\n"):
        insertion += "\n"
    updated = prefix + insertion + suffix
    return updated, True


def _extract_schema_additions(target: str, replacement: str) -> list[str]:
    target_lines = set(str(target or "").splitlines())
    additions: list[str] = []
    schema_tokens = (
        "db.Column(",
        "Column(",
        "ALTER TABLE",
        "CREATE TABLE",
        "ForeignKey(",
        "op.add_column(",
        "queryInterface.addColumn(",
        "prisma.",
    )
    for line in str(replacement or "").splitlines():
        if line in target_lines:
            continue
        if any(token in line for token in schema_tokens):
            additions.append(line.strip())
    return additions


def _schema_guard_issue(edits: list[dict]) -> Optional[str]:
    migration_markers = ("migrations/", "alembic/", "versions/", "prisma/", "schema.sql")
    has_migration_edit = any(
        any(marker in edit["resolved_file"].lower() for marker in migration_markers)
        for edit in edits
    )

    risky_edits: list[str] = []
    for edit in edits:
        file_path = edit["resolved_file"].lower()
        file_hints = ("model", "models/", "schema", "entity")
        if not any(hint in file_path for hint in file_hints):
            continue
        additions = _extract_schema_additions(edit.get("target", ""), edit.get("replacement", ""))
        risky_edits.extend(additions)

    if risky_edits and not has_migration_edit:
        sample = risky_edits[0]
        return (
            "Patch introduces a likely schema change without a migration edit. "
            f"Example added line: {sample}"
        )
    return None


def _anchor_diagnostics(edit: dict, repo_root: Path, retrieval_context: Optional[dict]) -> list[dict]:
    target = str(edit.get("target") or "")
    meaningful_lines = [
        line.strip()
        for line in target.splitlines()
        if line.strip() and len(line.strip()) >= 6 and line.strip() not in {"{", "}", "(", ")"}
    ]
    probes = meaningful_lines[:3]
    diagnostics: list[dict] = []

    if retrieval_context:
        ranked_files = retrieval_context.get("grounded_files") or retrieval_context.get("ranked_files", [])
    else:
        ranked_files = []
    for item in ranked_files[:4]:
        rel_path = _normalize_path(item.get("path"))
        if not rel_path:
            continue
        candidate = repo_root / rel_path
        if not candidate.exists():
            continue
        try:
            content = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        excerpts: list[str] = []
        lowered = content.lower()
        for probe in probes:
            idx = lowered.find(probe.lower())
            if idx == -1:
                continue
            start = max(0, idx - 160)
            end = min(len(content), idx + 360)
            excerpts.append(content[start:end].strip())

        diagnostics.append(
            {
                "file": rel_path,
                "matched_probes": len(excerpts),
                "excerpts": excerpts[:2],
            }
        )
    return diagnostics


def _build_necessity_scope(retrieval_context: Optional[dict], retry_context: Optional[dict]) -> set[str]:
    scope: set[str] = set()
    retrieval_context = retrieval_context or {}
    retry_context = retry_context or {}

    for item in (retrieval_context.get("grounded_files") or retrieval_context.get("ranked_files") or []):
        rel_path = _normalize_path(item.get("path"))
        if rel_path:
            scope.add(rel_path)

    validation_plan = retrieval_context.get("validation_plan") or retrieval_context.get("validation_context") or {}
    for test_path in (validation_plan.get("selected_test_paths") or []):
        rel_path = _normalize_path(test_path)
        if rel_path:
            scope.add(rel_path)

    failed_edit = retry_context.get("failed_edit") or {}
    for path in [failed_edit.get("requested_file"), failed_edit.get("resolved_file")]:
        rel_path = _normalize_path(path)
        if rel_path:
            scope.add(rel_path)

    for item in (retry_context.get("candidate_files") or []):
        rel_path = _normalize_path(item.get("path") if isinstance(item, dict) else item)
        if rel_path:
            scope.add(rel_path)

    return scope


def _preferred_service_root(retrieval_context: Optional[dict], preferred_service: str | None) -> str | None:
    normalized_service = str(preferred_service or "").strip().lower()
    if not normalized_service or normalized_service == "unknown":
        return None

    repo_profile = (retrieval_context or {}).get("repo_profile") or {}
    for service in repo_profile.get("services") or []:
        service_name = str(service.get("name") or "").strip().lower()
        service_language = str(service.get("language") or "").strip().lower()
        if normalized_service in {service_name, service_language}:
            root = _normalize_path(service.get("root") or ".")
            return root or "."

    if normalized_service.startswith("python"):
        for service in repo_profile.get("services") or []:
            if str(service.get("language") or "").strip().lower() == "python":
                return _normalize_path(service.get("root") or ".") or "."
    if normalized_service.startswith("node") or normalized_service.startswith("javascript"):
        for service in repo_profile.get("services") or []:
            if str(service.get("language") or "").strip().lower() == "javascript":
                return _normalize_path(service.get("root") or ".") or "."

    return None


def _is_within_service_root(resolved_file: str, service_root: str | None) -> bool:
    if not service_root:
        return True
    normalized_file = _normalize_path(resolved_file)
    normalized_root = _normalize_path(service_root)
    if normalized_root in {"", "."}:
        return True
    return normalized_file == normalized_root or normalized_file.startswith(f"{normalized_root}/")


def _is_path_necessary(
    resolved_file: str,
    operation: str,
    necessity_scope: set[str],
    allowed_service_root: str | None,
) -> tuple[bool, str | None]:
    if not _is_within_service_root(resolved_file, allowed_service_root):
        return False, "outside_incident_service"

    if not necessity_scope:
        return True, None
    normalized = _normalize_path(resolved_file)
    if normalized in necessity_scope:
        return True, None

    if operation == "create_file":
        lowered = normalized.lower()
        if any(token in lowered for token in ["migrations/", "alembic/", "versions/", "prisma/", "schema.sql"]):
            return True, None

    return False, "outside_retrieval_scope"


def _skip_state(reason: str, file_rel: str, confidence: float, threshold: float) -> AgentState:
    print(f"Skipping patch: {reason}")
    return {
        "patch_result": {
            "success": False,
            "file": file_rel,
            "modified_files": [],
            "diff_paths": [],
            "status": "skipped",
            "reason": reason,
            "error": f"Confidence {confidence}% below threshold {threshold}%",
        },
        "status": "skipped",
        "error": None,
        "retry_category": "low_confidence",
    }


def _fail_state(
    error_msg: str,
    *,
    status: str = "patch_failed",
    file_rel: str | None = None,
    edit_results: Optional[list[dict]] = None,
    anchor_diagnostics: Optional[list[dict]] = None,
    failed_edit: Optional[dict] = None,
    retry_category: str = "patch",
) -> AgentState:
    print(f"Patch failure: {error_msg}")
    return {
        "patch_result": {
            "success": False,
            "file": file_rel,
            "modified_files": [],
            "diff_paths": [],
            "edit_results": edit_results or [],
            "anchor_diagnostics": anchor_diagnostics or [],
            "failed_edit": failed_edit or {},
            "status": status,
            "reason": None,
            "error": error_msg,
        },
        "status": status,
        "error": error_msg,
        "retry_category": retry_category,
    }


def patch_code_node(state: AgentState) -> AgentState:
    print("\nPatch Code: starting...")

    fix = state.get("fix")
    ticket = state.get("ticket", {})
    ticket_key = ticket.get("jira_key", "UNKNOWN")
    retrieval_context = state.get("retrieval_context")
    repo_path = str(state.get("repo_path") or "").strip()
    if not repo_path:
        return _fail_state("Target repository path is missing in state", status="patch_failed")
    repo_root = Path(repo_path).resolve()

    if not fix:
        return _fail_state("No fix in state - run fix_generator_node first")

    confidence = float(fix.get("confidence", 0) or 0)
    fix_attempt = int(state.get("fix_attempt", 1) or 1)
    threshold = _effective_confidence_threshold(fix_attempt)
    edits = [dict(item) for item in (fix.get("edits") or [])]
    requested_file_rel = fix.get("primary_file", fix.get("file", ""))

    print(f"   Ticket     : {ticket_key}")
    print(f"   Attempt    : {fix_attempt}")
    print(f"   Repo       : {repo_root}")
    print(f"   Confidence : {confidence}%")
    print(f"   Threshold  : {threshold}%")
    print(f"   Edit count : {len(edits)}")

    if settings.PATCH_DISABLE_VALIDATIONS:
        print("   Patch validation mode: DISABLED (confidence/syntax/safety/schema checks bypassed)")
    elif confidence < threshold:
        return _skip_state(
            f"Confidence {confidence}% is below threshold {threshold}%",
            requested_file_rel,
            confidence,
            threshold,
        )

    if not edits:
        return _fail_state("No structured edits returned by fix generator", file_rel=requested_file_rel)

    prepared_edits: list[dict] = []
    edit_results: list[dict] = []
    staged_content: dict[str, str] = {}
    original_content_map: dict[str, str] = {}
    modified_files: list[str] = []
    checker = SafetyChecker()

    for index, raw_edit in enumerate(edits, start=1):
        edit = dict(raw_edit)
        edit["target"] = _clean_generated_code(edit.get("target", ""))
        edit["replacement"] = _clean_generated_code(edit.get("replacement", ""))
        operation = str(edit.get("operation") or "replace").strip().lower()
        edit["operation"] = operation

        try:
            target_path, resolved_file, resolution_source = _resolve_target_file(
                edit.get("file", ""),
                retrieval_context,
                repo_root,
                allow_create=(operation == "create_file"),
            )
        except FileNotFoundError as exc:
            return _fail_state(
                str(exc),
                status="file_resolution_failed",
                file_rel=edit.get("file"),
                edit_results=edit_results,
                failed_edit={
                    "index": index,
                    "requested_file": edit.get("file"),
                    "operation": operation,
                    "target": edit.get("target", "")[:4000],
                    "replacement": edit.get("replacement", "")[:4000],
                },
                retry_category="reanchor",
            )

        file_content = staged_content.get(resolved_file)
        if file_content is None:
            if target_path.exists():
                file_content = target_path.read_text(encoding="utf-8", errors="replace")
            else:
                file_content = ""
            original_content_map[resolved_file] = file_content

        edit["resolved_file"] = resolved_file
        edit["resolution_source"] = resolution_source

        print(f"   Edit {index:02d}   : {operation} -> {resolved_file} ({resolution_source})")

        try:
            updated_content, apply_info = _apply_edit_to_content(file_content, edit)
        except ValueError as exc:
            diagnostics = _anchor_diagnostics(edit, repo_root, retrieval_context)
            return _fail_state(
                f"Edit {index} could not be safely anchored: {exc}",
                status="match_failed",
                file_rel=resolved_file,
                edit_results=edit_results,
                anchor_diagnostics=diagnostics,
                failed_edit={
                    "index": index,
                    "requested_file": edit.get("file"),
                    "resolved_file": resolved_file,
                    "operation": operation,
                    "resolution_source": resolution_source,
                    "target": edit.get("target", "")[:6000],
                    "replacement": edit.get("replacement", "")[:6000],
                    "failure_reason": str(exc),
                },
                retry_category="reanchor",
            )

        if not settings.PATCH_DISABLE_VALIDATIONS:
            is_valid, syntax_error = _check_python_syntax(updated_content, resolved_file)
            if not is_valid:
                fallback_applied = False
                if resolved_file.endswith(".py") and operation in {"insert_after", "insert_before"}:
                    fallback_content, fallback_applied = _apply_python_import_fallback(
                        file_content,
                        edit.get("replacement", ""),
                    )
                    if fallback_applied:
                        is_valid, syntax_error = _check_python_syntax(fallback_content, resolved_file)
                        if is_valid:
                            updated_content = fallback_content
                            apply_info = dict(apply_info)
                            apply_info["strategy"] = f"{apply_info.get('strategy')}_python_import_fallback"
                if not is_valid:
                    return _fail_state(
                        syntax_error or "Syntax check failed after applying edit",
                        status="syntax_error",
                        file_rel=resolved_file,
                        edit_results=edit_results,
                        retry_category="patch",
                    )

            is_safe, issues = checker.check(updated_content, resolved_file)
            if not is_safe:
                return _fail_state(
                    f"Safety check failed for {resolved_file}: {issues}",
                    status="blocked",
                    file_rel=resolved_file,
                    edit_results=edit_results,
                    retry_category="patch",
                )

        staged_content[resolved_file] = updated_content
        prepared_edits.append(edit)
        if resolved_file not in modified_files:
            modified_files.append(resolved_file)
        edit_results.append(
            {
                "index": index,
                "requested_file": edit.get("file"),
                "resolved_file": resolved_file,
                "operation": operation,
                "strategy": apply_info["strategy"],
            }
        )

    if not settings.PATCH_DISABLE_VALIDATIONS:
        schema_issue = _schema_guard_issue(prepared_edits)
        if schema_issue:
            return _fail_state(
                schema_issue,
                status="schema_guard_failed",
                file_rel=requested_file_rel,
                edit_results=edit_results,
                retry_category="patch",
            )

    diff_paths: list[str] = []
    for rel_path in modified_files:
        original_content = original_content_map.get(rel_path, "")
        updated_content = staged_content[rel_path]
        target_path = repo_root / rel_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        diff_paths.append(_save_unified_diff(repo_root, original_content, updated_content, rel_path, ticket_key))
        target_path.write_text(updated_content, encoding="utf-8")

    applied_count = len(modified_files)
    skipped_count = 0
    noop_count = 0
    primary_file = modified_files[0] if modified_files else requested_file_rel
    print(f"   Patch applied: {', '.join(modified_files)}")
    patch_status = "patched"
    patch_success = True
    retry_category = "patch"
    error_message = None
    print(
        "   Patch summary: "
        f"applied_files={applied_count} skipped_edits={skipped_count} no_op_edits={noop_count}"
    )

    return {
        "patch_result": {
            "success": patch_success,
            "file": primary_file,
            "requested_file": requested_file_rel,
            "workspace_path": str(repo_root),
            "modified_files": modified_files,
            "diff_paths": diff_paths,
            "edit_results": edit_results,
            "summary": {
                "applied_files": applied_count,
                "skipped_edits": skipped_count,
                "no_op_edits": noop_count,
            },
            "status": patch_status,
            "reason": fix.get("reason"),
            "error": error_message,
        },
        "status": patch_status,
        "error": error_message,
        "retry_category": retry_category,
    }
