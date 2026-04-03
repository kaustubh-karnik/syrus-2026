from typing import Any, Dict
from pathlib import Path

from app.config import PROJECT_ROOT, settings
from app.agents.docker_autofix_agent import run_docker_autofix_after_clone
from app.mcp.github_client import (
    GitHubMCPClient,
    parse_owner_repo_from_url,
)


def _resolve_local_storage_path(raw_path: Any) -> str:
    candidate_value = str(raw_path or "").strip()
    if not candidate_value:
        candidate_value = str(settings.REPOS_BASE_DIR or "C:/data/repos")

    configured_base_value = str(settings.REPOS_BASE_DIR or "").strip()
    configured_base_path = Path(configured_base_value).expanduser() if configured_base_value else None
    configured_base_abs = (
        configured_base_path.resolve()
        if configured_base_path is not None and configured_base_path.is_absolute()
        else None
    )

    candidate_path = Path(candidate_value).expanduser()
    if candidate_path.is_absolute():
        return str(candidate_path.resolve())

    normalized_candidate = candidate_value.replace("\\", "/").strip()
    normalized_rel = normalized_candidate
    while normalized_rel.startswith("./"):
        normalized_rel = normalized_rel[2:]
    normalized_rel = normalized_rel.strip("/").strip()

    if configured_base_abs is not None:
        if not normalized_rel:
            return str(configured_base_abs)

        rel_leaf = Path(normalized_rel).name.strip()
        if rel_leaf and rel_leaf.lower() == configured_base_abs.name.lower():
            return str(configured_base_abs)

        candidate_path = (configured_base_abs / normalized_rel).resolve()
    else:
        candidate_path = (PROJECT_ROOT / candidate_path).resolve()

    return str(candidate_path)


def clone_repository_agent(payload: Dict[str, Any]) -> Dict[str, Any]:
    repo_id = (payload.get("repoId") or "").strip()
    repo_url = (payload.get("repoUrl") or "").strip()
    ref = (payload.get("ref") or "main").strip()
    local_storage_input = (
        payload.get("localStorageLocation")
        or settings.REPOS_BASE_DIR
        or "C:/data/repos"
    )
    local_storage = _resolve_local_storage_path(local_storage_input)
    auto_run_docker = bool(
        payload.get("autoRunDocker")
        if payload.get("autoRunDocker") is not None
        else settings.AUTO_RUN_DOCKER_AFTER_CLONE
    )

    if not repo_id:
        return {"status": "error", "message": "Missing required field: repoId"}

    print("\n[CloneAgent] Starting clone flow")
    print(
        f"[CloneAgent] repoId={repo_id} ref={ref} "
        f"localStorageInput={local_storage_input} localStorageResolved={local_storage}"
    )

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