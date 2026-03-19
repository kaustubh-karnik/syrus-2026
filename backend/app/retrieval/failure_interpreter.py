import hashlib
import re
from pathlib import Path
from typing import Any

from app.retrieval.cache_store import load_json_cache, repo_cache_token, save_json_cache


CACHE_VERSION = "v1"


def _flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts: list[str] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                if node.get("type") == "text" and node.get("text"):
                    parts.append(str(node.get("text")))
                for child in node.values():
                    walk(child)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(value)
        return "\n".join(parts)
    return str(value)


def _extract_stack_frames(text: str) -> list[dict]:
    frames: list[dict] = []

    py_pattern = re.compile(r'File\s+"(?P<file>[^"]+)",\s+line\s+(?P<line>\d+),\s+in\s+(?P<func>[A-Za-z0-9_<>]+)')
    js_pattern = re.compile(
        r"at\s+(?:(?P<func>[A-Za-z0-9_.$<>]+)\s+\()?(?P<file>[^\s:()]+\.[A-Za-z0-9]+):(?P<line>\d+)(?::\d+)?\)?"
    )

    for match in py_pattern.finditer(text):
        frames.append(
            {
                "file": str(match.group("file") or "").replace("\\", "/"),
                "line": int(match.group("line")),
                "symbol": match.group("func"),
                "language": "python",
            }
        )

    for match in js_pattern.finditer(text):
        file_value = str(match.group("file") or "")
        if not file_value or file_value.startswith("node: "):
            continue
        frames.append(
            {
                "file": file_value.replace("\\", "/"),
                "line": int(match.group("line")),
                "symbol": match.group("func") or "",
                "language": "javascript",
            }
        )

    deduped: list[dict] = []
    seen = set()
    for frame in frames:
        key = (frame.get("file"), frame.get("line"), frame.get("symbol"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(frame)
    return deduped[:12]


def _infer_error_type(text: str) -> str:
    lowered = text.lower()
    patterns = [
        ("module_not_found", ["modulenotfounderror", "cannot find module", "no module named"]),
        ("assertion_error", ["assertionerror", "expected", "received"]),
        ("null_pointer", ["none type", "nullpointer", "cannot read properties of null", "undefined"]),
        ("type_error", ["typeerror", "attributeerror", "unsupported operand"]),
        ("syntax_error", ["syntaxerror", "invalid syntax", "unexpected token"]),
        ("database_error", ["integrityerror", "operationalerror", "sql", "database", "alembic"]),
        ("http_error", ["http", "status code", "4xx", "5xx", "500 internal server error"]),
    ]
    for label, hints in patterns:
        if any(hint in lowered for hint in hints):
            return label
    return "runtime_error"


def _extract_endpoint(text: str) -> str | None:
    patterns = [
        re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[A-Za-z0-9_./-]*)", flags=re.IGNORECASE),
        re.compile(r'"(/api/[A-Za-z0-9_./-]+)"'),
    ]
    for pattern in patterns:
        match = pattern.search(text)
        if not match:
            continue
        endpoint = match.group(2) if pattern.groups >= 2 and match.lastindex and match.lastindex >= 2 else match.group(1)
        endpoint = str(endpoint or "").strip()
        if endpoint:
            return endpoint
    return None


def _extract_validation_targets(text: str, stack_frames: list[dict]) -> dict:
    test_paths: list[str] = []
    for pattern in [
        r"tests/test_[\w/.-]+\.py(?:::[\w:]+)?",
        r"[\w/.-]+\.py::[\w:]+",
        r"tests/[\w/.-]+\.(?:test|spec)\.[jt]sx?",
    ]:
        for match in re.findall(pattern, text or ""):
            if match not in test_paths:
                test_paths.append(str(match).replace("\\", "/"))

    stack_files = []
    for frame in stack_frames:
        file_value = str(frame.get("file") or "").replace("\\", "/")
        if file_value and file_value not in stack_files:
            stack_files.append(file_value)

    symbols = []
    for frame in stack_frames:
        symbol = str(frame.get("symbol") or "").strip()
        if symbol and symbol not in symbols:
            symbols.append(symbol)

    return {
        "test_paths": test_paths[:8],
        "stack_files": stack_files[:12],
        "symbols": symbols[:12],
    }


def interpret_failure(
    ticket: dict,
    *,
    retry_feedback: str | None = None,
    repo_root: Path | None = None,
    repo_state: dict | None = None,
) -> dict:
    summary = str(ticket.get("summary") or "")
    description = _flatten_text(ticket.get("description"))
    combined = "\n".join(part for part in [summary, description, str(retry_feedback or "")] if part).strip()

    cache_key_parts = [CACHE_VERSION, hashlib.sha1(combined.encode("utf-8", errors="ignore")).hexdigest()]
    if repo_root:
        token = repo_cache_token(repo_root, repo_state)
        cache_key_parts.insert(1, token)
        cached = load_json_cache(repo_root, "failure_interpretation", cache_key_parts)
        if isinstance(cached, dict):
            return cached

    stack_frames = _extract_stack_frames(combined)
    endpoint = _extract_endpoint(combined)
    error_type = _infer_error_type(combined)

    suspect_symbols = []
    for frame in stack_frames:
        symbol = str(frame.get("symbol") or "").strip()
        if symbol and symbol not in suspect_symbols:
            suspect_symbols.append(symbol)

    for token in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{3,}\b", combined):
        if token.lower() in {"error", "failed", "traceback", "assert", "tests"}:
            continue
        if token not in suspect_symbols and token[0].isalpha() and any(ch.isupper() for ch in token[1:]):
            suspect_symbols.append(token)
        if len(suspect_symbols) >= 14:
            break

    expected_behavior = ""
    expectation_match = re.search(r"(?:should|expected to|must)\s+([^\n.]{8,200})", combined, flags=re.IGNORECASE)
    if expectation_match:
        expected_behavior = expectation_match.group(1).strip()
    elif summary:
        expected_behavior = summary.strip()

    validation_targets = _extract_validation_targets(combined, stack_frames)

    payload = {
        "error_type": error_type,
        "stack_frames": stack_frames,
        "endpoint": endpoint,
        "suspect_symbols": suspect_symbols[:14],
        "expected_behavior": expected_behavior,
        "validation_targets": validation_targets,
        "raw_excerpt": combined[-2500:],
    }

    if repo_root:
        save_json_cache(repo_root, "failure_interpretation", cache_key_parts, payload)

    return payload
