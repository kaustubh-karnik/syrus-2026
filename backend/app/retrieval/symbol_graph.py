import ast
import re
from pathlib import Path

from app.retrieval.cache_store import load_json_cache, repo_cache_token, save_json_cache


SUPPORTED_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".sql"}
IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".syrus_cache",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "dist",
    "build",
}
CACHE_VERSION = "v1"


def _normalize_path(path: Path, repo_root: Path) -> str:
    try:
        rel_path = path.relative_to(repo_root)
    except ValueError:
        rel_path = path
    return str(rel_path).replace("\\", "/")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _iter_files(repo_root: Path):
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        yield path


def _service_for_path(repo_profile: dict, rel_path: str) -> str | None:
    best_service = None
    best_len = -1
    for service in repo_profile.get("services", []):
        root = str(service.get("root") or ".").strip()
        if root == ".":
            if best_service is None:
                best_service = service["name"]
            continue
        prefix = f"{root}/"
        if rel_path == root or rel_path.startswith(prefix):
            if len(prefix) > best_len:
                best_len = len(prefix)
                best_service = service["name"]
    return best_service or repo_profile.get("primary_service", {}).get("name")


def _resolve_python_imports(repo_root: Path, rel_path: str, content: str) -> list[str]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    current_dir = Path(rel_path).parent
    imports: list[str] = []

    def add_candidate(candidate: Path) -> None:
        absolute = (repo_root / candidate).resolve()
        if not str(absolute).startswith(str(repo_root.resolve())):
            return
        if absolute.exists() and absolute.is_file():
            normalized = _normalize_path(absolute, repo_root)
            if normalized not in imports:
                imports.append(normalized)

    def resolve_module(module_name: str, level: int) -> None:
        parts = [part for part in str(module_name or "").split(".") if part]
        bases = []
        if level > 0:
            base = current_dir
            for _ in range(max(0, level - 1)):
                base = base.parent
            bases.append(base)
        else:
            probe = current_dir
            while True:
                bases.append(probe)
                if str(probe) in {"", "."} or probe == Path("."):
                    break
                probe = probe.parent
            bases.append(Path("."))
        for base in bases:
            module_path = base.joinpath(*parts) if parts else base
            add_candidate(module_path.with_suffix(".py"))
            add_candidate(module_path / "__init__.py")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                resolve_module(alias.name, 0)
        elif isinstance(node, ast.ImportFrom):
            resolve_module(node.module or "", int(node.level or 0))
            for alias in node.names:
                if alias.name == "*":
                    continue
                module_parts = [part for part in str(node.module or "").split(".") if part]
                alias_parts = module_parts + [alias.name]
                base = current_dir
                for _ in range(max(0, int(node.level or 0) - 1)):
                    base = base.parent
                add_candidate(base.joinpath(*alias_parts).with_suffix(".py"))
    return imports[:12]


def _resolve_js_imports(repo_root: Path, rel_path: str, content: str) -> list[str]:
    current_dir = (repo_root / rel_path).parent
    imports: list[str] = []
    for match in re.findall(r"""(?:from|require\()\s*["']([^"']+)["']""", content):
        if not match.startswith("."):
            continue
        target = (current_dir / match).resolve()
        candidates = [
            target,
            target.with_suffix(".js"),
            target.with_suffix(".jsx"),
            target.with_suffix(".ts"),
            target.with_suffix(".tsx"),
            target / "index.js",
            target / "index.ts",
        ]
        for candidate in candidates:
            if not str(candidate).startswith(str(repo_root.resolve())):
                continue
            if candidate.exists() and candidate.is_file():
                normalized = _normalize_path(candidate, repo_root)
                if normalized not in imports:
                    imports.append(normalized)
                break
    return imports[:12]


def _python_symbols(content: str) -> list[dict]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    symbols: list[dict] = []
    lines = content.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = int(getattr(node, "lineno", 1))
        end = int(getattr(node, "end_lineno", start))
        decorators = []
        for decorator in getattr(node, "decorator_list", []):
            try:
                decorators.append(ast.unparse(decorator))
            except Exception:
                decorators.append(type(decorator).__name__)
        symbols.append(
            {
                "name": getattr(node, "name", ""),
                "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                "start_line": start,
                "end_line": end,
                "is_test": getattr(node, "name", "").startswith("test_"),
                "is_route": any(".get" in item or ".post" in item or ".route" in item for item in decorators),
                "decorators": decorators,
                "preview": "\n".join(lines[start - 1 : min(len(lines), end + 1)])[:800],
            }
        )
    return symbols


def _js_symbols(content: str) -> list[dict]:
    symbols: list[dict] = []
    for match in re.finditer(r"""(?:function|const|let|var)\s+([A-Za-z0-9_]+)\s*(?:=|\()""", content):
        name = match.group(1)
        symbols.append(
            {
                "name": name,
                "kind": "function",
                "start_line": content[: match.start()].count("\n") + 1,
                "end_line": content[: match.start()].count("\n") + 1,
                "is_test": name.lower().startswith("test"),
                "is_route": False,
                "decorators": [],
                "preview": content[match.start() : match.start() + 400],
            }
        )
    return symbols[:40]


def build_symbol_graph(repo_root: Path, repo_profile: dict, repo_state: dict | None = None) -> dict:
    token = repo_cache_token(repo_root, repo_state)
    cached = load_json_cache(repo_root, "symbol_graph", [CACHE_VERSION, token])
    if isinstance(cached, dict):
        return cached

    files: dict[str, dict] = {}
    reverse_imports: dict[str, list[str]] = {}
    edges: list[dict] = []
    summary = {
        "test_files": [],
        "route_files": [],
        "service_files": [],
        "model_files": [],
        "migration_files": [],
    }
    symbol_index: dict[str, list[dict]] = {}

    for path in _iter_files(repo_root):
        rel_path = _normalize_path(path, repo_root)
        content = _read_text(path)
        tags: list[str] = []
        lowered = rel_path.lower()

        if "/tests/" in f"/{lowered}" or Path(rel_path).name.startswith("test_"):
            tags.append("test_file")
            summary["test_files"].append(rel_path)
        if any(part in lowered for part in ["/routes/", "/route/", "/routers/"]):
            tags.append("route_file")
            summary["route_files"].append(rel_path)
        if any(part in lowered for part in ["/services/", "/service/"]):
            tags.append("service_file")
            summary["service_files"].append(rel_path)
        if any(part in lowered for part in ["/models/", "/model/", "/entities/", "/schemas/"]):
            tags.append("model_file")
            summary["model_files"].append(rel_path)
        if any(part in lowered for part in ["/migrations/", "/alembic/", "/versions/", "/prisma/"]):
            tags.append("migration_file")
            summary["migration_files"].append(rel_path)

        if path.suffix == ".py":
            imports = _resolve_python_imports(repo_root, rel_path, content)
            symbols = _python_symbols(content)
        elif path.suffix in {".js", ".jsx", ".ts", ".tsx"}:
            imports = _resolve_js_imports(repo_root, rel_path, content)
            symbols = _js_symbols(content)
        else:
            imports = []
            symbols = []

        files[rel_path] = {
            "path": rel_path,
            "service": _service_for_path(repo_profile, rel_path),
            "language": path.suffix.lower().lstrip(".") or "text",
            "imports": imports,
            "symbols": symbols,
            "tags": tags,
        }

        for symbol in symbols:
            symbol_name = str(symbol.get("name") or "").strip()
            if not symbol_name:
                continue
            symbol_index.setdefault(symbol_name, []).append(
                {
                    "path": rel_path,
                    "kind": symbol.get("kind"),
                    "start_line": symbol.get("start_line"),
                    "end_line": symbol.get("end_line"),
                }
            )

        for imported in imports:
            reverse_imports.setdefault(imported, []).append(rel_path)
            edges.append(
                {
                    "source_key": rel_path,
                    "target_key": imported,
                    "edge_type": "imports",
                }
            )

    for path_value, imported_by in reverse_imports.items():
        if path_value in files:
            files[path_value]["imported_by"] = sorted(imported_by)

    route_to_handler_map: dict[str, dict] = {}
    model_to_migration_map: dict[str, list[str]] = {}
    test_map: dict[str, list[str]] = {}

    migration_candidates = [
        rel for rel, info in files.items() if "migration_file" in set(info.get("tags") or [])
    ]
    test_files = [
        rel for rel, info in files.items() if "test_file" in set(info.get("tags") or [])
    ]

    for rel_path, file_info in files.items():
        tags = set(file_info.get("tags") or [])
        imports = set(file_info.get("imports") or [])

        if "route_file" in tags:
            route_symbols = [symbol for symbol in (file_info.get("symbols") or []) if symbol.get("is_route")]
            if route_symbols:
                route_to_handler_map[rel_path] = {
                    "handlers": [symbol.get("name") for symbol in route_symbols if symbol.get("name")],
                    "imports": [path for path in imports if path in files],
                }

        if "model_file" in tags:
            stem = Path(rel_path).stem.lower()
            linked = []
            for migration_path in migration_candidates:
                lowered = migration_path.lower()
                if stem and stem in lowered:
                    linked.append(migration_path)
                elif migration_path in imports:
                    linked.append(migration_path)
            model_to_migration_map[rel_path] = sorted(set(linked))[:8]

        related_tests = []
        for test_path in test_files:
            test_info = files.get(test_path) or {}
            if rel_path in set(test_info.get("imports") or []):
                related_tests.append(test_path)
                continue
            if Path(rel_path).stem.lower() in test_path.lower():
                related_tests.append(test_path)
        if related_tests:
            test_map[rel_path] = sorted(set(related_tests))[:8]

    payload = {
        "files": files,
        "graph_edges": edges[:400],
        "summary": {
            **summary,
            "route_to_handler_entries": len(route_to_handler_map),
            "model_to_migration_entries": len(model_to_migration_map),
            "test_map_entries": len(test_map),
            "symbol_count": sum(len(item.get("symbols") or []) for item in files.values()),
        },
        "symbol_index": symbol_index,
        "route_to_handler_map": route_to_handler_map,
        "model_to_migration_map": model_to_migration_map,
        "test_map": test_map,
    }
    save_json_cache(repo_root, "symbol_graph", [CACHE_VERSION, token], payload)
    return payload
