import re
from pathlib import Path

from app.retrieval.cache_store import load_json_cache, repo_cache_token, save_json_cache


IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".pipeline_cache",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".turbo",
}
CACHE_VERSION = "v2"
SERVICE_MARKERS = {
    "requirements.txt": "python",
    "pyproject.toml": "python",
    "setup.py": "python",
    "Pipfile": "python",
    "package.json": "javascript",
}
COMMON_ROUTE_DIRS = ["app/routes", "routes", "api/routes", "src/routes", "routers"]
COMMON_SERVICE_DIRS = ["app/services", "services", "src/services"]
COMMON_MODEL_DIRS = ["app/models", "models", "src/models", "entities", "schemas"]
COMMON_MIGRATION_DIRS = ["migrations", "alembic", "versions", "prisma"]


def _parse_requirements(service_root: Path) -> list[str]:
    requirements = service_root / "requirements.txt"
    if not requirements.exists():
        return []
    deps: list[str] = []
    for raw_line in _read_text(requirements).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        dep = re.split(r"[<>=~! ]", line, maxsplit=1)[0].strip()
        if dep and dep.lower() not in {item.lower() for item in deps}:
            deps.append(dep)
        if len(deps) >= 40:
            break
    return deps


def _parse_package_json_deps(service_root: Path) -> list[str]:
    package_json = service_root / "package.json"
    if not package_json.exists():
        return []
    text = _read_text(package_json)
    deps: list[str] = []
    for block in ["dependencies", "devDependencies"]:
        block_match = re.search(rf'"{block}"\s*:\s*\{{(.*?)\}}', text, flags=re.DOTALL)
        if not block_match:
            continue
        for dep_match in re.finditer(r'"([@A-Za-z0-9_./-]+)"\s*:\s*"[^"]+"', block_match.group(1)):
            dep = dep_match.group(1)
            if dep and dep.lower() not in {item.lower() for item in deps}:
                deps.append(dep)
            if len(deps) >= 40:
                break
    return deps


def _infer_test_runner(service_root: Path, language: str, frameworks: list[str]) -> str:
    dependency_text = "\n".join(
        _read_text(path).lower()
        for path in [
            service_root / "requirements.txt",
            service_root / "pyproject.toml",
            service_root / "setup.py",
            service_root / "package.json",
        ]
        if path.exists()
    )
    if language == "python":
        if "pytest" in dependency_text or "pytest" in frameworks:
            return "pytest"
        if (service_root / "unittest.cfg").exists() or "unittest" in dependency_text:
            return "unittest"
        return "pytest" if any((service_root / item).exists() for item in ["pytest.ini", "conftest.py"]) else "unittest"
    if language == "javascript":
        if "vitest" in dependency_text:
            return "vitest"
        if "jest" in dependency_text:
            return "jest"
        return "npm-test"
    return "unknown"


def _infer_migration_system(service_root: Path, frameworks: list[str], language: str) -> str:
    if (service_root / "alembic.ini").exists() or "alembic" in frameworks:
        return "alembic"
    if (service_root / "manage.py").exists() and "django" in frameworks:
        return "django-migrations"
    if (service_root / "prisma").exists() or (service_root / "schema.prisma").exists():
        return "prisma"
    if language == "javascript" and (service_root / "migrations").exists():
        return "sequelize-or-custom"
    return "none"


def _normalize_path(value: Path, repo_root: Path) -> str:
    try:
        rel_path = value.relative_to(repo_root)
    except ValueError:
        rel_path = value
    return str(rel_path).replace("\\", "/")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _iter_depth(repo_root: Path, max_depth: int = 3):
    for path in repo_root.rglob("*"):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        try:
            rel_parts = path.relative_to(repo_root).parts
        except ValueError:
            rel_parts = path.parts
        if len(rel_parts) > max_depth + 1:
            continue
        yield path


def _discover_service_roots(repo_root: Path) -> list[dict]:
    discovered: dict[str, dict] = {}

    for path in _iter_depth(repo_root, max_depth=3):
        if not path.is_file():
            continue
        language = SERVICE_MARKERS.get(path.name)
        if not language:
            continue
        root = path.parent
        rel_root = _normalize_path(root, repo_root) or "."
        service_name = root.name if rel_root != "." else "repo-root"
        discovered[rel_root] = {
            "name": service_name,
            "root": rel_root,
            "language": language,
        }

    if not discovered:
        discovered["."] = {
            "name": "repo-root",
            "root": ".",
            "language": "python" if (repo_root / "requirements.txt").exists() else "unknown",
        }

    return sorted(discovered.values(), key=lambda item: (item["root"] != ".", item["root"]))


def _collect_candidate_dirs(service_root: Path, patterns: list[str], repo_root: Path) -> list[str]:
    found: list[str] = []
    for pattern in patterns:
        candidate = service_root / pattern
        if candidate.exists() and candidate.is_dir():
            found.append(_normalize_path(candidate, repo_root))
    return found


def _parse_compose_service_names(repo_root: Path) -> tuple[list[str], list[str]]:
    compose_files = []
    for name in ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]:
        candidate = repo_root / name
        if candidate.exists():
            compose_files.append(_normalize_path(candidate, repo_root))

    service_names: list[str] = []
    for rel_path in compose_files:
        text = _read_text(repo_root / rel_path)
        in_services = False
        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if re.match(r"^services\s*:\s*$", stripped):
                in_services = True
                continue
            if in_services:
                if re.match(r"^[A-Za-z0-9_-]+\s*:\s*$", stripped) and len(line) - len(line.lstrip(" ")) <= 2:
                    name = stripped[:-1]
                    if name not in service_names:
                        service_names.append(name)
                elif len(line) - len(line.lstrip(" ")) == 0 and not stripped.startswith("-"):
                    in_services = False
    return compose_files, service_names


def _detect_frameworks(repo_root: Path, service_root: Path, language: str) -> list[str]:
    frameworks: list[str] = []
    dependency_files = [
        service_root / "requirements.txt",
        service_root / "pyproject.toml",
        service_root / "setup.py",
        service_root / "package.json",
    ]
    combined = "\n".join(_read_text(path).lower() for path in dependency_files if path.exists())

    sample_sources = []
    for candidate in [
        service_root / "app",
        service_root / "src",
        service_root,
    ]:
        if not candidate.exists():
            continue
        for path in candidate.rglob("*"):
            if any(part in IGNORED_DIRS for part in path.parts) or not path.is_file():
                continue
            if language == "python" and path.suffix != ".py":
                continue
            if language == "javascript" and path.suffix not in {".js", ".ts", ".jsx", ".tsx"}:
                continue
            sample_sources.append(_read_text(path)[:2000].lower())
            if len(sample_sources) >= 6:
                break
        if len(sample_sources) >= 6:
            break

    source_text = "\n".join(sample_sources)
    searchable = "\n".join([combined, source_text])
    candidates = (
        {
            "flask": ["flask", "@app.route", "blueprint("],
            "fastapi": ["fastapi", "@router.", "apirouter("],
            "django": ["django", "urlpatterns", "from django"],
            "sqlalchemy": ["sqlalchemy", "db.model", "declarative_base", "sessionmaker"],
            "pytest": ["pytest", "def test_", "import pytest"],
            "alembic": ["alembic", "op.add_column", "upgrade()"],
        }
        if language == "python"
        else {
            "express": ["express", "router.get(", "router.post("],
            "sequelize": ["sequelize", "model.init(", "findall("],
            "jest": ["jest", "describe(", "it("],
        }
    )
    for name, hints in candidates.items():
        if any(hint in searchable for hint in hints):
            frameworks.append(name)
    return frameworks


def profile_repository(repo_root: Path, repo_state: dict | None = None) -> dict:
    token = repo_cache_token(repo_root, repo_state)
    cached = load_json_cache(repo_root, "repo_profile", [CACHE_VERSION, token])
    if isinstance(cached, dict):
        return cached

    compose_files, compose_service_names = _parse_compose_service_names(repo_root)
    services = []
    languages = set()

    for service in _discover_service_roots(repo_root):
        service_root = repo_root if service["root"] == "." else repo_root / service["root"]
        language = service["language"]
        languages.add(language)
        frameworks = _detect_frameworks(repo_root, service_root, language)
        service_profile = {
            **service,
            "frameworks": frameworks,
            "test_roots": _collect_candidate_dirs(service_root, ["tests", "test"], repo_root),
            "route_dirs": _collect_candidate_dirs(service_root, COMMON_ROUTE_DIRS, repo_root),
            "service_dirs": _collect_candidate_dirs(service_root, COMMON_SERVICE_DIRS, repo_root),
            "model_dirs": _collect_candidate_dirs(service_root, COMMON_MODEL_DIRS, repo_root),
            "migration_dirs": _collect_candidate_dirs(service_root, COMMON_MIGRATION_DIRS, repo_root),
            "entrypoints": [
                rel_path
                for rel_path in [
                    _normalize_path(service_root / "app.py", repo_root),
                    _normalize_path(service_root / "main.py", repo_root),
                    _normalize_path(service_root / "manage.py", repo_root),
                    _normalize_path(service_root / "app" / "__init__.py", repo_root),
                    _normalize_path(service_root / "src" / "index.js", repo_root),
                ]
                if (repo_root / rel_path).exists()
            ],
            "package_manager": (
                "npm"
                if (service_root / "package.json").exists()
                else "pip"
                if (service_root / "requirements.txt").exists() or (service_root / "setup.py").exists()
                else "poetry"
                if (service_root / "pyproject.toml").exists()
                else "unknown"
            ),
            "test_runner": _infer_test_runner(service_root, language, frameworks),
            "migration_system": _infer_migration_system(service_root, frameworks, language),
            "dependency_graph": {
                "direct_dependencies": (
                    _parse_requirements(service_root)
                    if language == "python"
                    else _parse_package_json_deps(service_root)
                    if language == "javascript"
                    else []
                )
            },
        }
        services.append(service_profile)

    if not services:
        services.append(
            {
                "name": "repo-root",
                "root": ".",
                "language": "unknown",
                "frameworks": [],
                "test_roots": [],
                "route_dirs": [],
                "service_dirs": [],
                "model_dirs": [],
                "migration_dirs": [],
                "entrypoints": [],
                "package_manager": "unknown",
                "test_runner": "unknown",
                "migration_system": "none",
                "dependency_graph": {"direct_dependencies": []},
            }
        )

    primary_service = services[0]
    for service in services:
        if service["language"] != "unknown":
            primary_service = service
            break

    payload = {
        "cache_token": token,
        "repo_root": str(repo_root),
        "languages": sorted(languages) or ["unknown"],
        "primary_language": primary_service["language"],
        "services": services,
        "primary_service": {
            "name": primary_service["name"],
            "root": primary_service["root"],
            "language": primary_service["language"],
        },
        "compose_files": compose_files,
        "compose_service_names": compose_service_names,
        "has_docker_compose": bool(compose_files),
        "frameworks": sorted({framework for service in services for framework in service["frameworks"]}),
        "test_runners": sorted({str(service.get("test_runner") or "unknown") for service in services}),
        "migration_systems": sorted({str(service.get("migration_system") or "none") for service in services}),
    }
    save_json_cache(repo_root, "repo_profile", [CACHE_VERSION, token], payload)
    return payload
