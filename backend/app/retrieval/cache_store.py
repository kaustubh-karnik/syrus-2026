import hashlib
import json
from pathlib import Path
from typing import Any


def cache_root(repo_root: Path) -> Path:
    return repo_root / ".syrus_cache"


def _cache_file(repo_root: Path, namespace: str, key_parts: list[str]) -> Path:
    joined = "::".join(str(part or "") for part in key_parts)
    digest = hashlib.sha1(joined.encode("utf-8")).hexdigest()
    return cache_root(repo_root) / namespace / f"{digest}.json"


def repo_cache_token(repo_root: Path, repo_state: dict | None) -> str:
    repo_state = repo_state or {}
    commit_sha = str(repo_state.get("commit_sha") or "").strip()
    if commit_sha and not repo_state.get("dirty"):
        return f"commit:{commit_sha}"

    file_count = 0
    max_mtime_ns = 0
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        if ".git" in path.parts or ".syrus_cache" in path.parts:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        file_count += 1
        max_mtime_ns = max(max_mtime_ns, int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))))
    return f"dirty:{file_count}:{max_mtime_ns}"


def load_json_cache(repo_root: Path, namespace: str, key_parts: list[str]) -> Any:
    cache_path = _cache_file(repo_root, namespace, key_parts)
    if not cache_path.exists():
        return None
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_json_cache(repo_root: Path, namespace: str, key_parts: list[str], payload: Any) -> None:
    cache_path = _cache_file(repo_root, namespace, key_parts)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
