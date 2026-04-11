from typing import Any, Dict
from pathlib import Path
import os

from app.config import PROJECT_ROOT, settings, resolve_path_to_absolute
from app.agents.docker_autofix_agent import run_docker_autofix_after_clone
from app.mcp.github_client import (
    GitHubMCPClient,
    parse_owner_repo_from_url,
)


def _is_within(parent: Path, child: Path) -> bool:
    parent_resolved = parent.resolve()
    child_resolved = child.resolve()
    try:
        child_resolved.relative_to(parent_resolved)
        return True
    except ValueError:
        return False


def _validate_repo_id(repo_id: str) -> str:
    value = str(repo_id or "").strip().replace("\\", "/")
    if not value:
        raise ValueError("Missing required field: repoId")
    if value.startswith("/") or value.startswith("../") or "/../" in f"/{value}/":
        raise ValueError("Invalid repoId: path traversal is not allowed")
    return value


def _resolve_local_storage_path(raw_path: Any) -> str:
    candidate_value = str(raw_path or "").strip()
    if not candidate_value:
        candidate_value = str(settings.REPOS_BASE_DIR or "").strip()
    if not candidate_value:
        raise ValueError(
            "Missing localStorageLocation. Provide an absolute folder path where the repository should be cloned."
        )

    candidate_path = Path(candidate_value).expanduser()
    if not candidate_path.is_absolute():
        raise ValueError(
            "localStorageLocation must be an absolute path (example: C:/Users/<you>/repos)."
        )

    resolved = candidate_path.resolve()
    project_root = Path(PROJECT_ROOT).resolve()
    if _is_within(project_root, resolved):
        raise ValueError(
            "localStorageLocation must be outside this project repository. Choose a folder outside MPM-Build."
        )

    return str(resolved)


def clone_repository_agent(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        repo_id = _validate_repo_id(payload.get("repoId"))
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    repo_url = (payload.get("repoUrl") or "").strip()
    ref = (payload.get("ref") or "main").strip()
    local_storage_input = payload.get("localStorageLocation") or settings.REPOS_BASE_DIR
    try:
        local_storage = _resolve_local_storage_path(local_storage_input)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    auto_run_docker = bool(
        payload.get("autoRunDocker")
        if payload.get("autoRunDocker") is not None
        else settings.AUTO_RUN_DOCKER_AFTER_CLONE
    )

    print("\n[CloneAgent] Starting clone flow")
    print(f"[CloneAgent] repoId={repo_id}")
    print(f"[CloneAgent] ref={ref}")
    print(f"[CloneAgent] localStorageInput (from frontend)={local_storage_input}")
    print(f"[CloneAgent] localStorageResolved (absolute)={local_storage}")
    print(f"[CloneAgent] os.path.isabs(localStorageResolved)={os.path.isabs(local_storage)}")

    if not repo_url:
        github_repo = (settings.GITHUB_REPO or "").strip()
        if github_repo:
            if github_repo.startswith("http://") or github_repo.startswith("https://"):
                repo_url = github_repo
            else:
                repo_url = f"https://github.com/{github_repo.replace('.git', '')}.git"

    if not repo_url:
        return {"status": "error", "message": "Missing repoUrl"}

    print(f"[CloneAgent] repoUrl={repo_url}")
    print(f"[CloneAgent] autoRunDocker={auto_run_docker}")

    owner_repo = parse_owner_repo_from_url(repo_url)

    client = GitHubMCPClient(
        github_token=settings.GITHUB_TOKEN,
        mcp_server_command=settings.GITHUB_MCP_SERVER_COMMAND,
        mcp_server_args=settings.GITHUB_MCP_SERVER_ARGS,
    )

    try:
        print("[CloneAgent] Probing repository via MCP (if possible)...")
        if owner_repo is not None:
            owner, repo = owner_repo
            mcp_probe = client.probe_repository_with_mcp(owner, repo, ref)
        else:
            mcp_probe = {
                "status": "skipped",
                "message": "Could not infer OWNER/REPO for MCP probe, clone continued with repoUrl",
            }
        print("[CloneAgent] Cloning/updating repository...")
        clone_result = client.clone_or_update_repository(repo_url, repo_id, ref, local_storage)
        print(
            "[CloneAgent] Clone complete: "
            f"operation={clone_result.get('operation')} localPath={clone_result.get('localPath')}"
        )

        response = {
            "status": "ok",
            "repoId": repo_id,
            "repoUrl": repo_url,
            "ref": ref,
            "localPath": clone_result["localPath"],
            "commitSha": clone_result["commitSha"],
            "operation": clone_result["operation"],
            "mcp": mcp_probe,
        }
        if auto_run_docker:
            print("[CloneAgent] Starting post-clone docker auto-heal...")
            response["dockerAutoHeal"] = run_docker_autofix_after_clone(clone_result["localPath"], repo_id)
            print(f"[CloneAgent] Docker auto-heal status={response['dockerAutoHeal'].get('status')}")
        else:
            response["dockerAutoHeal"] = {
                "status": "skipped",
                "message": "autoRunDocker disabled",
            }
            print("[CloneAgent] Docker auto-heal skipped")
        print("[CloneAgent] Finished clone flow")
        return response
    except Exception as exc:
        return {"status": "error", "message": str(exc)}