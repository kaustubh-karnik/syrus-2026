import re
from pathlib import Path

from app.retrieval.cache_store import load_json_cache, repo_cache_token, save_json_cache


CACHE_VERSION = "v1"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _python_route_symbols(file_info: dict) -> list[dict]:
    routes = []
    for symbol in file_info.get("symbols") or []:
        decorators = [str(item or "") for item in (symbol.get("decorators") or [])]
        if any(
            token in decorator
            for decorator in decorators
            for token in [".get", ".post", ".put", ".delete", ".patch", ".route", "api_view", "action("]
        ):
            routes.append(symbol)
    return routes


def _extract_django_patterns(content: str) -> list[str]:
    patterns = []
    for match in re.findall(r"""(?:path|re_path|url)\(\s*["']([^"']+)["']""", content):
        if match not in patterns:
            patterns.append(match)
    return patterns


def build_framework_context(repo_root: Path, repo_profile: dict, symbol_graph: dict, repo_state: dict | None = None) -> dict:
    token = repo_cache_token(repo_root, repo_state)
    cached = load_json_cache(repo_root, "framework_context", [CACHE_VERSION, token])
    if isinstance(cached, dict):
        return cached

    files = symbol_graph.get("files") or {}
    adapters = []
    route_chains = []
    file_annotations: dict[str, dict] = {}
    summary = {
        "route_files": [],
        "service_files": [],
        "model_files": [],
        "test_files": [],
        "urlconf_files": [],
    }

    service_frameworks = {}
    for service in repo_profile.get("services") or []:
        service_frameworks[str(service.get("name"))] = list(service.get("frameworks") or [])

    for path, file_info in files.items():
        rel_path = str(path)
        service_name = str(file_info.get("service") or "")
        frameworks = service_frameworks.get(service_name, list(repo_profile.get("frameworks") or []))
        annotations = {
            "frameworks": frameworks,
            "roles": [],
            "routes": [],
            "related_paths": [],
        }
        tags = set(file_info.get("tags") or [])

        if "route_file" in tags:
            annotations["roles"].append("route_file")
            summary["route_files"].append(rel_path)
        if "service_file" in tags:
            annotations["roles"].append("service_file")
            summary["service_files"].append(rel_path)
        if "model_file" in tags:
            annotations["roles"].append("model_file")
            summary["model_files"].append(rel_path)
        if "test_file" in tags:
            annotations["roles"].append("test_file")
            summary["test_files"].append(rel_path)

        if rel_path.endswith("urls.py") and "django" in frameworks:
            annotations["roles"].append("urlconf_file")
            summary["urlconf_files"].append(rel_path)
            content = _read_text(repo_root / rel_path)
            django_routes = _extract_django_patterns(content)
            for route in django_routes:
                annotations["routes"].append({"path": route, "symbol": "urlpatterns", "kind": "django"})

        python_routes = _python_route_symbols(file_info) if rel_path.endswith(".py") else []
        for symbol in python_routes:
            decorators = [str(item or "") for item in (symbol.get("decorators") or [])]
            route_paths = []
            for decorator in decorators:
                for match in re.findall(r"""["'](/?[^"']*)["']""", decorator):
                    if "/" in match or match:
                        route_paths.append(match)
            annotations["routes"].append(
                {
                    "path": route_paths[0] if route_paths else None,
                    "symbol": symbol.get("name"),
                    "kind": "python_decorator",
                }
            )

        related = []
        if "route_file" in annotations["roles"] or "urlconf_file" in annotations["roles"]:
            for imported in file_info.get("imports") or []:
                imported_info = files.get(imported) or {}
                imported_tags = set(imported_info.get("tags") or [])
                if imported_tags & {"service_file", "model_file"}:
                    related.append(imported)
            if not related:
                for imported in file_info.get("imports") or []:
                    if imported not in related:
                        related.append(imported)
        elif "test_file" in annotations["roles"]:
            for imported in file_info.get("imports") or []:
                imported_info = files.get(imported) or {}
                imported_tags = set(imported_info.get("tags") or [])
                if imported_tags & {"route_file", "service_file", "model_file"}:
                    related.append(imported)

        annotations["related_paths"] = related[:8]
        file_annotations[rel_path] = annotations

        if annotations["routes"]:
            route_chains.append(
                {
                    "file": rel_path,
                    "service": service_name,
                    "frameworks": frameworks,
                    "routes": annotations["routes"],
                    "related_paths": annotations["related_paths"],
                }
            )

    adapters = sorted({framework for item in file_annotations.values() for framework in item.get("frameworks") or []})
    payload = {
        "adapters": adapters,
        "file_annotations": file_annotations,
        "route_chains": route_chains,
        "summary": summary,
    }
    save_json_cache(repo_root, "framework_context", [CACHE_VERSION, token], payload)
    return payload
