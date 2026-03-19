import difflib
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable


ATTEMPTS_DIR_NAME = ".syrus_attempts"
BACKUPS_DIR_NAME = "backups"
IGNORED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".next",
    ".turbo",
    "node_modules",
    ".syrus_attempts",
    "backups",
}
IGNORED_FILE_NAMES = {
    ".DS_Store",
}


def _safe_ticket_segment(ticket_key: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in (ticket_key or "UNKNOWN"))
    return cleaned or "UNKNOWN"


def _attempts_root(base_repo: Path) -> Path:
    return base_repo / ATTEMPTS_DIR_NAME


def _workspace_dir(base_repo: Path, ticket_key: str, attempt: int) -> Path:
    ticket_segment = _safe_ticket_segment(ticket_key)
    return _attempts_root(base_repo) / f"{ticket_segment}_attempt_{attempt}"


def _ignore_paths(_src: str, names: list[str]) -> set[str]:
    ignored = set()
    for name in names:
        lowered = name.lower()
        if name in IGNORED_FILE_NAMES or name in IGNORED_DIR_NAMES or lowered.endswith(".pyc"):
            ignored.add(name)
    return ignored


def _remove_readonly(_func, path: str, _exc_info) -> None:
    os.chmod(path, 0o700)
    target = Path(path)
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
    elif target.exists():
        os.unlink(path)


def create_attempt_workspace(base_repo_path: str, ticket_key: str, attempt: int) -> dict:
    base_repo = Path(base_repo_path).resolve()
    if not base_repo.exists():
        raise FileNotFoundError(f"Target repository does not exist: {base_repo}")

    attempts_root = _attempts_root(base_repo)
    attempts_root.mkdir(parents=True, exist_ok=True)

    workspace = _workspace_dir(base_repo, ticket_key, attempt)
    if workspace.exists():
        shutil.rmtree(workspace, onerror=_remove_readonly)

    shutil.copytree(
        base_repo,
        workspace,
        ignore=_ignore_paths,
    )

    return {
        "base_repo_path": str(base_repo),
        "workspace_path": str(workspace),
        "ticket_key": ticket_key,
        "attempt": attempt,
    }


def cleanup_attempt_workspace(workspace_path: str) -> None:
    if not workspace_path:
        return

    workspace = Path(workspace_path)
    if workspace.exists():
        shutil.rmtree(workspace, onerror=_remove_readonly)

    parent = workspace.parent
    if parent.exists():
        try:
            next(parent.iterdir())
        except StopIteration:
            parent.rmdir()


def _write_diff(base_repo: Path, rel_path: str, original_text: str, updated_text: str, ticket_key: str) -> str:
    backups_dir = base_repo / BACKUPS_DIR_NAME
    backups_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_path = rel_path.replace("/", "_").replace("\\", "_")
    diff_path = backups_dir / f"{_safe_ticket_segment(ticket_key)}_{safe_path}_{timestamp}.diff"

    diff_lines = difflib.unified_diff(
        original_text.splitlines(keepends=True),
        updated_text.splitlines(keepends=True),
        fromfile=f"a/{rel_path}",
        tofile=f"b/{rel_path}",
        lineterm="",
    )
    diff_path.write_text("\n".join(diff_lines), encoding="utf-8")
    return str(diff_path)


def promote_workspace_changes(
    base_repo_path: str,
    workspace_path: str,
    modified_files: Iterable[str],
    ticket_key: str,
) -> dict:
    base_repo = Path(base_repo_path).resolve()
    workspace = Path(workspace_path).resolve()
    promoted_files: list[str] = []
    diff_paths: list[str] = []

    for rel_path in modified_files:
        rel = str(rel_path or "").replace("\\", "/").strip()
        if not rel:
            continue

        source = workspace / rel
        destination = base_repo / rel
        if not source.exists():
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)

        original_text = ""
        if destination.exists():
            original_text = destination.read_text(encoding="utf-8", errors="replace")
        updated_text = source.read_text(encoding="utf-8", errors="replace")

        if destination.exists() and original_text == updated_text:
            continue

        diff_paths.append(_write_diff(base_repo, rel, original_text, updated_text, ticket_key))
        shutil.copy2(source, destination)
        promoted_files.append(rel)

    return {
        "success": True,
        "promoted_files": promoted_files,
        "diff_paths": diff_paths,
    }
