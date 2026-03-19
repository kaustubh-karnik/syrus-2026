import re
from pathlib import Path

from app.retrieval.cache_store import load_json_cache, repo_cache_token, save_json_cache


MAX_SELECTED_TESTS = 4
CACHE_VERSION = "v1"


def _tokenize(values: list[str]) -> list[str]:
    tokens: list[str] = []
    seen = set()
    for value in values:
        for raw in re.findall(r"[A-Za-z0-9_./:-]+", str(value or "").lower()):
            cleaned = raw.strip("._/-:")
            if len(cleaned) < 3 or cleaned in seen:
                continue
            tokens.append(cleaned)
            seen.add(cleaned)
    return tokens


def _infer_service(repo_profile: dict, paths: list[str], preferred_service: str | None) -> dict:
    services = list(repo_profile.get("services") or [])
    if not services:
        return {
            "name": "repo-root",
            "root": ".",
            "language": repo_profile.get("primary_language") or "unknown",
            "test_roots": ["tests"],
            "package_manager": "unknown",
        }

    if preferred_service:
        normalized = str(preferred_service).strip().lower()
        for service in services:
            if normalized in {str(service.get("name") or "").lower(), str(service.get("language") or "").lower()}:
                return service

    best = services[0]
    best_score = -1
    for service in services:
        root = str(service.get("root") or ".").strip()
        prefix = "" if root == "." else f"{root}/"
        score = 0
        for path in paths:
            normalized = str(path or "").replace("\\", "/")
            if prefix and normalized.startswith(prefix):
                score += 20
            elif root == ".":
                score += 2
        if score > best_score:
            best_score = score
            best = service
    return best


def _extract_explicit_tests(text: str) -> list[str]:
    explicit: list[str] = []
    for pattern in [
        r"tests/test_[\w/.-]+\.py(?:::[\w:]+)?",
        r"[\w/.-]+\.py::[\w:]+",
        r"tests/[\w/.-]+\.(?:test|spec)\.[jt]sx?",
    ]:
        for match in re.findall(pattern, text or ""):
            if match not in explicit:
                explicit.append(match)
    return explicit


def _match_docker_service(service: dict, repo_profile: dict) -> str | None:
    compose_services = list(repo_profile.get("compose_service_names") or [])
    if not compose_services:
        return None

    candidates = [
        str(service.get("name") or ""),
        str(service.get("root") or "").split("/")[-1],
        str(service.get("language") or ""),
        "python-service" if service.get("language") == "python" else "",
        "node-service" if service.get("language") == "javascript" else "",
        "backend" if service.get("language") == "python" else "",
    ]
    for candidate in candidates:
        lowered = candidate.strip().lower()
        if not lowered:
            continue
        for compose_name in compose_services:
            if lowered == compose_name.lower() or lowered in compose_name.lower():
                return compose_name
    return compose_services[0]


def _dependency_services(repo_profile: dict, primary_service_name: str | None) -> list[str]:
    compose_services = list(repo_profile.get("compose_service_names") or [])
    supporting = []
    for name in compose_services:
        lowered = name.lower()
        if primary_service_name and lowered == primary_service_name.lower():
            continue
        if any(token in lowered for token in ["postgres", "redis", "mysql", "mongo", "db", "cache", "rabbit"]):
            supporting.append(name)
    return supporting


def _local_test_command(language: str) -> list[str]:
    if language == "python":
        return ["python", "-m", "pytest"]
    if language == "javascript":
        return ["npm", "test", "--", "--runTestsByPath"]
    return []


def build_validation_plan(
    repo_root: Path,
    repo_profile: dict,
    symbol_graph: dict,
    *,
    ticket: dict | None = None,
    terms: list[str] | None = None,
    likely_files: list[str] | None = None,
    modified_files: list[str] | None = None,
    preferred_service: str | None = None,
    failure_text: str | None = None,
    failure_signals: dict | None = None,
) -> dict:
    ticket = ticket or {}
    terms = [str(item or "") for item in (terms or []) if item is not None]
    likely_files = [str(item or "").replace("\\", "/") for item in (likely_files or []) if item]
    modified_files = [str(item or "").replace("\\", "/") for item in (modified_files or []) if item]
    failure_text = str(failure_text or "")
    failure_signals = failure_signals or {}

    cache_token = str(repo_profile.get("cache_token") or repo_cache_token(repo_root, {"commit_sha": None, "dirty": True}))
    cached = load_json_cache(
        repo_root,
        "validation_plan",
        [
            CACHE_VERSION,
            cache_token,
            str(preferred_service or ""),
            "||".join(sorted(terms)),
            "||".join(sorted(likely_files)),
            "||".join(sorted(modified_files)),
            failure_text[-400:],
            str(failure_signals.get("error_type") or ""),
            str(failure_signals.get("endpoint") or ""),
        ],
    )
    if isinstance(cached, dict):
        return cached

    service = _infer_service(repo_profile, [*likely_files, *modified_files], preferred_service)
    service_root = str(service.get("root") or ".")
    language = str(service.get("language") or repo_profile.get("primary_language") or "unknown")

    graph_files = symbol_graph.get("files") or {}
    test_candidates = []
    tokens = _tokenize(
        [
            *terms,
            *likely_files,
            *modified_files,
            ticket.get("summary") or "",
            ticket.get("description") or "",
            failure_text,
            str(failure_signals.get("error_type") or ""),
            str(failure_signals.get("endpoint") or ""),
            *[str(item) for item in (failure_signals.get("suspect_symbols") or [])],
        ]
    )
    explicit_tests = _extract_explicit_tests(failure_text)
    explicit_tests.extend(str(item) for item in ((failure_signals.get("validation_targets") or {}).get("test_paths") or []))
    explicit_tests.extend(path for path in likely_files if "/tests/" in f"/{path.lower()}" or Path(path).name.startswith("test_"))
    explicit_tests = list(dict.fromkeys(explicit_tests))
    service_test_roots = [str(item or "").replace("\\", "/") for item in (service.get("test_roots") or [])]

    for path, file_info in graph_files.items():
        tags = set(file_info.get("tags") or [])
        if "test_file" not in tags:
            continue
        if service_root != "." and not path.startswith(f"{service_root}/"):
            continue
        score = 0
        lowered = path.lower()
        for token in tokens:
            if token in lowered:
                score += 25
            for symbol in file_info.get("symbols") or []:
                preview = str(symbol.get("preview") or "").lower()
                name = str(symbol.get("name") or "").lower()
                if token in name:
                    score += 18
                if token in preview:
                    score += 8
        for related in [*likely_files, *modified_files]:
            stem = Path(related).stem.lower()
            parent = Path(related).parent.name.lower()
            if stem and stem in lowered:
                score += 60
            if parent and parent in lowered:
                score += 20
        for test_root in service_test_roots:
            if test_root and (path == test_root or path.startswith(f"{test_root}/")):
                score += 45
        if path in explicit_tests or any(path == item.split("::", 1)[0] for item in explicit_tests):
            score += 200
        test_candidates.append(
            {
                "repo_path": path,
                "score": score,
            }
        )

    test_candidates.sort(key=lambda item: (item["score"], item["repo_path"]), reverse=True)
    preferred_root_candidates = [
        item
        for item in test_candidates
        if any(
            test_root and (item["repo_path"] == test_root or item["repo_path"].startswith(f"{test_root}/"))
            for test_root in service_test_roots
        )
    ]
    if preferred_root_candidates and any(item["score"] > 0 for item in preferred_root_candidates):
        test_candidates = preferred_root_candidates + [
            item for item in test_candidates if item not in preferred_root_candidates
        ]

    selected_tests = []
    for explicit in explicit_tests:
        if explicit not in selected_tests:
            selected_tests.append(explicit)
    for item in test_candidates:
        if len(selected_tests) >= MAX_SELECTED_TESTS:
            break
        if item["score"] <= 0 and selected_tests:
            break
        if item["repo_path"] not in selected_tests:
            selected_tests.append(item["repo_path"])

    default_test_target = selected_tests or list(service.get("test_roots") or []) or ["tests"]
    execution_candidates = []

    local_command = _local_test_command(language)
    if local_command:
        execution_candidates.append(
            {
                "mode": "local",
                "confidence": 0.7 if language in {"python", "javascript"} else 0.4,
                "test_command_base": local_command,
                "build_command": None,
                "dependency_commands": {},
                "workdir": service_root,
            }
        )

    docker_service = None
    if repo_profile.get("has_docker_compose"):
        docker_service = _match_docker_service(service, repo_profile)
        if docker_service:
            docker_confidence = 0.45
            if str(service.get("name") or "").lower() in docker_service.lower():
                docker_confidence += 0.2
            if service_root not in {"", "."} and service_root.split("/")[-1].lower() in docker_service.lower():
                docker_confidence += 0.2
            if language == "python" and "python" in docker_service.lower():
                docker_confidence += 0.15
            if language == "javascript" and any(token in docker_service.lower() for token in ["node", "web", "frontend"]):
                docker_confidence += 0.15

            docker_test_command = (
                ["docker", "compose", "run", "--rm", docker_service, "python", "-m", "pytest"]
                if language == "python"
                else ["docker", "compose", "run", "--rm", docker_service, "npm", "test", "--", "--runTestsByPath"]
                if language == "javascript"
                else []
            )
            deps = _dependency_services(repo_profile, docker_service)
            execution_candidates.append(
                {
                    "mode": "docker",
                    "confidence": docker_confidence,
                    "docker_service": docker_service,
                    "test_command_base": docker_test_command,
                    "build_command": ["docker", "compose", "build", "--no-cache", docker_service] if docker_test_command else None,
                    "dependency_commands": {
                        "up": ["docker", "compose", "up", "-d", *deps],
                        "down": ["docker", "compose", "down", "--remove-orphans"],
                        "services": deps,
                    }
                    if deps
                    else {},
                    "workdir": ".",
                }
            )

    execution_candidates.sort(key=lambda item: item.get("confidence", 0), reverse=True)
    selected_candidate = execution_candidates[0] if execution_candidates else {}
    payload = {
        "source": "repo_profile+symbol_graph",
        "service": {
            "name": service.get("name"),
            "root": service_root,
            "language": language,
        },
        "execution_mode": selected_candidate.get("mode") or "local",
        "docker_service": selected_candidate.get("docker_service"),
        "build_command": selected_candidate.get("build_command"),
        "test_command_base": selected_candidate.get("test_command_base") or [],
        "command_args": default_test_target,
        "selected_test_paths": selected_tests,
        "display": selected_tests or default_test_target,
        "candidate_tests": test_candidates[:12],
        "dependency_commands": selected_candidate.get("dependency_commands") or {},
        "execution_candidates": execution_candidates,
    }
    if service.get("test_roots"):
        payload["test_roots"] = list(service.get("test_roots") or [])
    save_json_cache(
        repo_root,
        "validation_plan",
        [
            CACHE_VERSION,
            cache_token,
            str(preferred_service or ""),
            "||".join(sorted(terms)),
            "||".join(sorted(likely_files)),
            "||".join(sorted(modified_files)),
            failure_text[-400:],
        ],
        payload,
    )
    return payload
