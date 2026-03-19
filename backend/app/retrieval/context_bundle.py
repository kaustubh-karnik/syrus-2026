import json
import re
import subprocess
from pathlib import Path
from typing import Iterable

from app.retrieval.cache_store import load_json_cache, repo_cache_token, save_json_cache
from app.retrieval.framework_adapters import build_framework_context
from app.retrieval.repo_profiler import profile_repository
from app.retrieval.symbol_graph import build_symbol_graph
from app.retrieval.validation_planner import build_validation_plan


MAX_SEED_FILES = 6
MAX_GROUNDED_FILES = 10
MAX_PREVIEW_CHARS = 1800
MAX_HISTORY_PATHS = 8
CACHE_VERSION = "v2"


def normalize_path(value: str) -> str:
    return str(value or "").replace("\\", "/").strip()


def tokenize(terms: Iterable[str]) -> list[str]:
    tokens: list[str] = []
    seen = set()
    for term in terms:
        for raw in re.findall(r"[A-Za-z0-9_./:-]+", str(term or "").lower()):
            cleaned = raw.strip("._/-:")
            if len(cleaned) < 3 or cleaned in seen:
                continue
            tokens.append(cleaned)
            seen.add(cleaned)
    return tokens


def anchor_terms(retry_context: dict | None) -> list[str]:
    if not retry_context:
        return []
    failed_edit = retry_context.get("failed_edit") or {}
    target = str(failed_edit.get("target") or "")
    lines: list[str] = []
    for line in target.splitlines():
        stripped = line.strip()
        if len(stripped) < 6:
            continue
        if stripped in {"{", "}", "(", ")"}:
            continue
        lines.append(stripped)
    return lines[:6]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _run_git(repo_root: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=12,
            check=False,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def detect_repo_state(repo_root: Path, requested_commit_sha: str | None) -> dict:
    commit_sha = _run_git(repo_root, ["rev-parse", "HEAD"])
    branch = _run_git(repo_root, ["rev-parse", "--abbrev-ref", "HEAD"])
    status = _run_git(repo_root, ["status", "--short"])
    requested = str(requested_commit_sha or "").strip()
    return {
        "repo_root": str(repo_root),
        "is_git_repo": bool(commit_sha),
        "branch": branch or None,
        "commit_sha": commit_sha or None,
        "requested_commit_sha": requested or None,
        "commit_aligned": not requested or not commit_sha or requested == commit_sha,
        "dirty": bool(status),
    }


def _history_related_paths(repo_root: Path, repo_state: dict, seed_paths: list[str]) -> list[str]:
    if not repo_state.get("is_git_repo") or not seed_paths:
        return []

    token = repo_cache_token(repo_root, repo_state)
    cached = load_json_cache(repo_root, "history_related_paths", [CACHE_VERSION, token, *seed_paths[:3]])
    if isinstance(cached, list):
        return [normalize_path(item) for item in cached if item]

    cochanged: dict[str, int] = {}
    for seed_path in seed_paths[:3]:
        output = _run_git(repo_root, ["log", "--pretty=format:", "--name-only", "-n", "20", "--", seed_path])
        if not output:
            continue
        for raw_line in output.splitlines():
            rel_path = normalize_path(raw_line)
            if not rel_path or rel_path == normalize_path(seed_path):
                continue
            cochanged[rel_path] = cochanged.get(rel_path, 0) + 1

    ranked = [path for path, _ in sorted(cochanged.items(), key=lambda item: (item[1], item[0]), reverse=True)]
    result = ranked[:MAX_HISTORY_PATHS]
    save_json_cache(repo_root, "history_related_paths", [CACHE_VERSION, token, *seed_paths[:3]], result)
    return result


def _score_seed_file(
    path: str,
    file_info: dict,
    tokens: list[str],
    likely_files: list[str],
    preferred_service: str | None,
    retry_context: dict | None,
    mcp_candidate_paths: list[str],
    history_paths: list[str],
) -> float:
    score = 0.0
    lowered = path.lower()
    basename = Path(path).name.lower()
    likely_norm = [normalize_path(item).lower() for item in likely_files]
    likely_basenames = {Path(item).name.lower() for item in likely_norm}

    if lowered in likely_norm:
        score += 260
    if basename in likely_basenames:
        score += 180
    if lowered in [item.lower() for item in mcp_candidate_paths]:
        score += 120
    if lowered in [item.lower() for item in history_paths]:
        score += 90

    if preferred_service and str(file_info.get("service") or "").lower() == preferred_service.lower():
        score += 50

    for tag in file_info.get("tags") or []:
        if tag == "route_file":
            score += 48
        elif tag == "service_file":
            score += 38
        elif tag == "model_file":
            score += 30
        elif tag == "test_file":
            score += 8
        elif tag == "migration_file":
            score += 18

    symbol_names = [str(symbol.get("name") or "").lower() for symbol in (file_info.get("symbols") or [])]
    preview_text = " ".join(symbol_names)
    for token in tokens:
        if token in basename:
            score += 55
        if token in lowered:
            score += 22
        if token in preview_text:
            score += 10

    failed_edit = (retry_context or {}).get("failed_edit") or {}
    for candidate in [failed_edit.get("requested_file"), failed_edit.get("resolved_file")]:
        normalized = normalize_path(candidate).lower()
        if normalized and lowered == normalized:
            score += 240

    for anchor in anchor_terms(retry_context):
        lowered_anchor = anchor.lower()
        if lowered_anchor in preview_text or lowered_anchor in lowered:
            score += 40

    return score


def _framework_boost(path: str, framework_context: dict, likely_files: list[str]) -> float:
    annotations = (framework_context.get("file_annotations") or {}).get(path) or {}
    score = 0.0
    roles = set(annotations.get("roles") or [])
    if "route_file" in roles:
        score += 60
    if "service_file" in roles:
        score += 45
    if "model_file" in roles:
        score += 35
    if "urlconf_file" in roles:
        score += 35
    if "test_file" in roles and any("/tests/" not in f"/{item.lower()}" for item in likely_files):
        score -= 10
    if annotations.get("routes"):
        score += 30
    return score


def _seed_files(
    symbol_graph: dict,
    *,
    tokens: list[str],
    likely_files: list[str],
    preferred_service: str | None,
    retry_context: dict | None,
    mcp_candidate_paths: list[str],
    history_paths: list[str],
) -> list[dict]:
    ranked = []
    for path, file_info in (symbol_graph.get("files") or {}).items():
        score = _score_seed_file(
            path,
            file_info,
            tokens,
            likely_files,
            preferred_service,
            retry_context,
            mcp_candidate_paths,
            history_paths,
        )
        if score <= 0:
            continue
        reasons = ["local_graph_discovery"]
        if normalize_path(path) in [normalize_path(item) for item in mcp_candidate_paths]:
            reasons.append("github_mcp_discovery")
        if normalize_path(path) in [normalize_path(item) for item in history_paths]:
            reasons.append("git_history_cochange")
        ranked.append(
            {
                "path": path,
                "score": float(score),
                "similarity": round(min(score / 320.0, 1.0), 4),
                "relation_reasons": reasons,
                "symbol_name": "",
            }
        )
    ranked.sort(key=lambda item: (item["score"], item["path"]), reverse=True)
    return ranked[:MAX_SEED_FILES]


def _merge_candidate(candidate_map: dict[str, dict], path: str, score: float, reason: str) -> None:
    normalized = normalize_path(path)
    if not normalized:
        return
    entry = candidate_map.setdefault(
        normalized,
        {
            "path": normalized,
            "score": 0.0,
            "relation_reasons": [],
        },
    )
    entry["score"] += score
    if reason not in entry["relation_reasons"]:
        entry["relation_reasons"].append(reason)


def _select_grounded_paths(
    candidate_map: dict[str, dict],
    graph_files: dict[str, dict],
    framework_context: dict,
    max_files: int,
) -> list[str]:
    route_service_model = []
    tests = []
    migrations = []
    others = []

    annotations = framework_context.get("file_annotations") or {}
    for candidate in sorted(candidate_map.values(), key=lambda item: (item["score"], item["path"]), reverse=True):
        path = normalize_path(candidate.get("path"))
        if not path or path not in graph_files:
            continue
        roles = set((annotations.get(path) or {}).get("roles") or [])
        tags = set(graph_files.get(path, {}).get("tags") or [])
        if roles & {"route_file", "service_file", "model_file", "urlconf_file"} or tags & {"route_file", "service_file", "model_file"}:
            route_service_model.append(path)
        elif "migration_file" in roles or "migration_file" in tags:
            migrations.append(path)
        elif "test_file" in roles or "test_file" in tags:
            tests.append(path)
        else:
            others.append(path)

    selected: list[str] = []
    for group, limit in [(route_service_model, 5), (migrations, 1), (others, 2), (tests, 2)]:
        for path in group:
            if len(selected) >= max_files:
                break
            if path not in selected:
                selected.append(path)
            if sum(1 for item in selected if item in group) >= limit:
                break
    for path in route_service_model + migrations + others + tests:
        if len(selected) >= max_files:
            break
        if path not in selected:
            selected.append(path)
    return selected[:max_files]


def _same_directory_siblings(repo_root: Path, rel_path: str) -> list[str]:
    directory = (repo_root / rel_path).parent
    if not directory.exists():
        return []
    siblings = []
    for child in sorted(directory.iterdir()):
        if not child.is_file():
            continue
        candidate = normalize_path(child.relative_to(repo_root))
        if candidate != normalize_path(rel_path):
            siblings.append(candidate)
    return siblings[:4]


def _focused_content(path: str, content: str, file_info: dict, tokens: list[str]) -> tuple[str, str, int | None, int | None]:
    lines = content.splitlines()
    best_symbol = None
    best_score = 0
    for symbol in file_info.get("symbols") or []:
        snippet = str(symbol.get("preview") or "")
        symbol_score = sum(1 for token in tokens if token in str(symbol.get("name") or "").lower() or token in snippet.lower())
        if symbol_score > best_score:
            best_score = symbol_score
            best_symbol = symbol

    if best_symbol:
        return (
            str(best_symbol.get("preview") or "")[:MAX_PREVIEW_CHARS],
            str(best_symbol.get("name") or ""),
            best_symbol.get("start_line"),
            best_symbol.get("end_line"),
        )

    lowered = content.lower()
    for token in tokens:
        idx = lowered.find(token.lower())
        if idx == -1:
            continue
        start = max(0, idx - 240)
        end = min(len(content), idx + MAX_PREVIEW_CHARS)
        return content[start:end].strip(), "", None, None

    return content[:MAX_PREVIEW_CHARS].strip(), "", None, None


def _evidence_coverage(
    grounded_files: list[dict],
    failure_signals: dict,
    repo_state: dict,
) -> dict:
    grounded_paths = {normalize_path(item.get("path", "")).lower() for item in grounded_files}
    stack_files = [
        normalize_path(frame.get("file", "")).lower()
        for frame in (failure_signals.get("stack_frames") or [])
        if frame.get("file")
    ]
    top_stack = stack_files[0] if stack_files else ""
    validation_targets = failure_signals.get("validation_targets") or {}
    expected_tests = [normalize_path(item).lower() for item in (validation_targets.get("test_paths") or []) if item]
    suspect_symbols = [str(item or "").lower() for item in (failure_signals.get("suspect_symbols") or []) if item]

    top_stack_included = bool(top_stack and any(top_stack.endswith(path) or path.endswith(top_stack) for path in grounded_paths))
    tests_included = bool(
        not expected_tests
        or any(any(test.endswith(path) or path.endswith(test) for path in grounded_paths) for test in expected_tests)
    )
    symbol_found = bool(
        not suspect_symbols
        or any(
            symbol in str(item.get("focused_content") or "").lower() or symbol in str(item.get("symbol_name") or "").lower()
            for symbol in suspect_symbols
            for item in grounded_files
        )
    )
    commit_aligned = bool(repo_state.get("commit_aligned", True))

    checks = [top_stack_included, tests_included, symbol_found, commit_aligned]
    score = round(sum(1 for value in checks if value) / len(checks), 3)
    return {
        "score": score,
        "top_stack_frame_included": top_stack_included,
        "validation_targets_included": tests_included,
        "suspect_symbol_included": symbol_found,
        "repo_state_aligned": commit_aligned,
    }


def build_context_bundle(
    repo_root: Path,
    *,
    ticket: dict,
    terms: list[str],
    likely_files: list[str],
    service: str | None,
    bug_type: str | None,
    root_cause_hint: str | None,
    failure_signals: dict | None,
    retry_context: dict | None,
    requested_commit_sha: str | None,
    mcp_candidate_paths: list[str],
    mcp_history_paths: list[str] | None = None,
    github_binding: dict | None = None,
) -> dict:
    repo_state = detect_repo_state(repo_root, requested_commit_sha)
    failure_signals = failure_signals or {}

    cache_key = [
        CACHE_VERSION,
        repo_cache_token(repo_root, repo_state),
        str(service or ""),
        str(bug_type or ""),
        str(root_cause_hint or ""),
        "||".join(sorted(normalize_path(item) for item in likely_files if item)),
        "||".join(sorted(normalize_path(item) for item in (mcp_candidate_paths or []) if item)),
        "||".join(sorted(normalize_path(item) for item in (mcp_history_paths or []) if item)),
        json.dumps(failure_signals, ensure_ascii=True, sort_keys=True)[:1400],
        json.dumps(retry_context or {}, ensure_ascii=True, sort_keys=True)[:1400],
        str(ticket.get("jira_key") or ""),
    ]
    cached = load_json_cache(repo_root, "context_bundle", cache_key)
    if isinstance(cached, dict):
        return cached

    repo_profile = profile_repository(repo_root, repo_state=repo_state)
    symbol_graph = build_symbol_graph(repo_root, repo_profile, repo_state=repo_state)
    framework_context = build_framework_context(repo_root, repo_profile, symbol_graph, repo_state=repo_state)

    search_terms = [
        *terms,
        *likely_files,
        bug_type or "",
        root_cause_hint or "",
        failure_signals.get("error_type") or "",
        failure_signals.get("endpoint") or "",
        *[str(item) for item in (failure_signals.get("suspect_symbols") or [])],
        *[str(item.get("file") or "") for item in (failure_signals.get("stack_frames") or [])],
        *[str(item) for item in ((failure_signals.get("validation_targets") or {}).get("test_paths") or [])],
        ticket.get("summary") or "",
        ticket.get("description") or "",
    ]
    token_list = tokenize(search_terms)
    early_seed_paths = [normalize_path(path) for path in likely_files if path]
    early_seed_paths.extend(normalize_path(path) for path in mcp_candidate_paths[:3] if path)
    history_paths = _history_related_paths(repo_root, repo_state, early_seed_paths)
    for path in mcp_history_paths or []:
        normalized = normalize_path(path)
        if normalized and normalized not in history_paths:
            history_paths.insert(0, normalized)

    seed_files = _seed_files(
        symbol_graph,
        tokens=token_list,
        likely_files=likely_files,
        preferred_service=service,
        retry_context=retry_context,
        mcp_candidate_paths=mcp_candidate_paths,
        history_paths=history_paths,
    )

    validation_plan = build_validation_plan(
        repo_root,
        repo_profile,
        symbol_graph,
        ticket=ticket,
        terms=search_terms,
        likely_files=likely_files,
        modified_files=[],
        preferred_service=service,
        failure_signals=failure_signals,
    )

    candidate_map: dict[str, dict] = {}
    for item in seed_files:
        boost = _framework_boost(item["path"], framework_context, likely_files)
        _merge_candidate(candidate_map, item["path"], float(item["score"]) + boost, "seed_path")

    for path in mcp_candidate_paths:
        _merge_candidate(candidate_map, path, 85, "github_mcp_discovery")
    for path in history_paths:
        _merge_candidate(candidate_map, path, 90, "git_history_cochange")
    for path in validation_plan.get("selected_test_paths") or []:
        _merge_candidate(candidate_map, path, 110, "selected_test_context")
    for frame in failure_signals.get("stack_frames") or []:
        frame_file = normalize_path(frame.get("file"))
        if frame_file:
            _merge_candidate(candidate_map, frame_file, 180, "stack_frame_signal")
    for path in (failure_signals.get("validation_targets") or {}).get("test_paths") or []:
        _merge_candidate(candidate_map, path, 140, "failure_validation_target")

    failed_edit = (retry_context or {}).get("failed_edit") or {}
    for path in [
        failed_edit.get("resolved_file"),
        failed_edit.get("requested_file"),
        *((retry_context or {}).get("candidate_files") or []),
    ]:
        if isinstance(path, dict):
            path = path.get("path")
        _merge_candidate(candidate_map, str(path or ""), 220, "retry_reanchor")

    graph_files = symbol_graph.get("files") or {}
    route_to_handler_map = symbol_graph.get("route_to_handler_map") or {}
    model_to_migration_map = symbol_graph.get("model_to_migration_map") or {}
    test_map = symbol_graph.get("test_map") or {}
    framework_annotations = framework_context.get("file_annotations") or {}
    for seed in seed_files[:3]:
        path = seed.get("path")
        file_info = graph_files.get(path) or {}
        annotations = framework_annotations.get(path) or {}
        for imported in file_info.get("imports") or []:
            imported_roles = set((framework_annotations.get(imported) or {}).get("roles") or [])
            import_score = 95
            if imported_roles & {"service_file", "model_file", "route_file"}:
                import_score += 45
            _merge_candidate(candidate_map, imported, import_score, "import_dependency")
        for importer in file_info.get("imported_by") or []:
            _merge_candidate(candidate_map, importer, 70, "reverse_import_dependency")
        for sibling in _same_directory_siblings(repo_root, path):
            _merge_candidate(candidate_map, sibling, 45, "same_directory_sibling")

        tags = set(file_info.get("tags") or [])
        roles = set(annotations.get("roles") or [])
        if "route_file" in tags:
            for candidate_path, candidate_info in graph_files.items():
                candidate_tags = set(candidate_info.get("tags") or [])
                if "service_file" in candidate_tags or "model_file" in candidate_tags:
                    if candidate_info.get("service") == file_info.get("service"):
                        _merge_candidate(candidate_map, candidate_path, 35, "implementation_neighbor")
        if "model_file" in tags:
            for candidate_path, candidate_info in graph_files.items():
                if "migration_file" in set(candidate_info.get("tags") or []):
                    if candidate_info.get("service") == file_info.get("service"):
                        _merge_candidate(candidate_map, candidate_path, 40, "schema_neighbor")
            for migration_path in model_to_migration_map.get(path) or []:
                _merge_candidate(candidate_map, migration_path, 85, "model_migration_map")
        for handler_path in route_to_handler_map.get(path, {}).get("imports") or []:
            _merge_candidate(candidate_map, handler_path, 75, "route_handler_map")
        for related_test in test_map.get(path) or []:
            _merge_candidate(candidate_map, related_test, 68, "test_map")
        for related in annotations.get("related_paths") or []:
            related_roles = set((framework_annotations.get(related) or {}).get("roles") or [])
            framework_score = 80 if related_roles & {"service_file", "model_file", "route_file"} else 55
            _merge_candidate(candidate_map, related, framework_score, "framework_chain")

    for chain in framework_context.get("route_chains") or []:
        for related in chain.get("related_paths") or []:
            _merge_candidate(candidate_map, related, 65, "route_chain_neighbor")

    grounded_files = []
    graph_edges = []
    selected_grounded_paths = _select_grounded_paths(candidate_map, graph_files, framework_context, MAX_GROUNDED_FILES)
    for rel_path in selected_grounded_paths:
        candidate = candidate_map.get(rel_path) or {"score": 0.0, "relation_reasons": []}
        if not rel_path:
            continue
        absolute = (repo_root / rel_path).resolve()
        if not str(absolute).startswith(str(repo_root.resolve())):
            continue
        if not absolute.exists() or not absolute.is_file():
            continue
        content = _read_text(absolute)
        if not content:
            continue
        file_info = graph_files.get(rel_path) or {}
        preview, symbol_name, start_line, end_line = _focused_content(rel_path, content, file_info, token_list)
        grounded_files.append(
            {
                "path": rel_path,
                "language": absolute.suffix.lower().lstrip(".") or "text",
                "symbol_name": symbol_name,
                "similarity": round(min(float(candidate["score"]) / 320.0, 1.0), 4),
                "score": float(candidate["score"]),
                "relation_reasons": list(candidate.get("relation_reasons") or []),
                "content_preview": preview[:700],
                "focused_content": preview,
                "start_line": start_line,
                "end_line": end_line,
                "content": content,
            }
        )
        for imported in (file_info.get("imports") or [])[:4]:
            graph_edges.append(
                {
                    "source_key": rel_path,
                    "target_key": imported,
                    "edge_type": "imports",
                }
            )
        if len(grounded_files) >= MAX_GROUNDED_FILES:
            break

    blocks = [
        "# Retrieval Source",
        "Hybrid retrieval: repo profiling + symbol graph + validation planning + local grounding",
    ]
    for item in grounded_files:
        blocks.append(
            "\n".join(
                [
                    f"# File: {item['path']}",
                    f"# Reasons: {','.join(item.get('relation_reasons', []))}",
                    item.get("focused_content", "")[:MAX_PREVIEW_CHARS],
                ]
            )
        )

    coverage = _evidence_coverage(grounded_files, failure_signals, repo_state)

    payload = {
        "query": " ".join(str(item) for item in search_terms if item),
        "source": "repo_adaptive_grounding",
        "repo_state": repo_state,
        "repo_profile": repo_profile,
        "failure_signals": failure_signals,
        "evidence_coverage": coverage,
        "framework_context_summary": framework_context.get("summary") or {},
        "symbol_graph_summary": symbol_graph.get("summary") or {},
        "validation_plan": validation_plan,
        "validation_context": validation_plan,
        "seed_files": seed_files,
        "grounded_files": grounded_files,
        "ranked_files": grounded_files,
        "graph_edges": graph_edges[:24],
        "context_text": "\n---\n".join(blocks),
        "discovery_paths": [item.get("path") for item in grounded_files if item.get("path")],
        "remote_signals": {
            "github_binding": github_binding or {},
            "mcp_candidate_paths": [normalize_path(item) for item in mcp_candidate_paths if item],
            "history_related_paths": history_paths,
        },
    }
    save_json_cache(repo_root, "context_bundle", cache_key, payload)
    return payload
