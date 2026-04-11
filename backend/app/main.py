import json
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from jira.exceptions import JIRAError
from pydantic import BaseModel

from app.agents.github_clone_agent import clone_repository_agent
from app.agents.pipeline import run_pipeline_sequential, run_pipeline_with_retries
from app.agents.ticket_analyzer import ticket_analyzer_node
from app.agents.vector_search import vector_search_node
from app.config import PROJECT_ROOT, settings
from app.mcp.github_client import GitHubMCPClient, parse_owner_repo_from_url, parse_repo_owner_name
from app.mcp.jira_client import JiraMCPClient
from app.services.ticket_service import TicketService

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ticket_service = TicketService()


PIPELINE_REPORT_START_MARKER = "PIPELINE_REPORT_JSON_START"
PIPELINE_REPORT_END_MARKER = "PIPELINE_REPORT_JSON_END"
_pipeline_run_state: dict = {
    "status": "idle",
    "startedAt": None,
    "finishedAt": None,
    "exitCode": None,
    "logs": "",
    "report": None,
    "stopRequested": False,
    "stopReason": None,
    "wasStopped": False,
    "targetRepoPath": None,
    "targetRepoId": None,
    "targetRepoUrl": None,
}
_pipeline_lock = threading.Lock()
_pipeline_process: Optional[subprocess.Popen] = None
_pipeline_stop_requested = False
_pipeline_stop_reason: Optional[str] = None
_active_repo_context_file = Path(PROJECT_ROOT) / ".active_repo_context.json"

_active_repo_context: dict = {
    "repoPath": None,
    "repoId": None,
    "repoUrl": None,
    "ref": None,
}


def _is_within(parent: Path, child: Path) -> bool:
    parent_resolved = parent.resolve()
    child_resolved = child.resolve()
    try:
        child_resolved.relative_to(parent_resolved)
        return True
    except ValueError:
        return False


def _normalize_runtime_repo_path(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""

    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        return ""

    resolved = candidate.resolve()
    project_root = Path(PROJECT_ROOT).resolve()
    if _is_within(project_root, resolved):
        return ""

    return str(resolved)


def _load_active_repo_context_from_disk() -> None:
    if not _active_repo_context_file.exists():
        return

    try:
        payload = json.loads(_active_repo_context_file.read_text(encoding="utf-8"))
    except Exception:
        return

    if not isinstance(payload, dict):
        return

    for key in ["repoPath", "repoId", "repoUrl", "ref"]:
        value = str(payload.get(key) or "").strip()
        _active_repo_context[key] = value or None


def _save_active_repo_context_to_disk() -> None:
    payload = {
        "repoPath": str(_active_repo_context.get("repoPath") or "").strip() or None,
        "repoId": str(_active_repo_context.get("repoId") or "").strip() or None,
        "repoUrl": str(_active_repo_context.get("repoUrl") or "").strip() or None,
        "ref": str(_active_repo_context.get("ref") or "").strip() or None,
    }
    try:
        _active_repo_context_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass


_load_active_repo_context_from_disk()


def _resolve_runtime_repo_context() -> dict:
    repo_path = _normalize_runtime_repo_path(_active_repo_context.get("repoPath"))
    repo_id = str(_active_repo_context.get("repoId") or "").strip()
    repo_url = str(_active_repo_context.get("repoUrl") or "").strip()
    ref = str(_active_repo_context.get("ref") or "").strip()

    if not repo_id:
        repo_id = str(settings.TARGET_REPO_ID or "").strip()
    if not repo_url:
        repo_url = str(settings.GITHUB_REPO or "").strip()
    if not ref:
        ref = str(settings.GITHUB_BASE_BRANCH or "main").strip() or "main"

    return {
        "repoPath": repo_path,
        "repoId": repo_id,
        "repoUrl": repo_url,
        "ref": ref,
    }


def _require_runtime_repo_path(runtime_context: dict) -> str:
    repo_path = str(runtime_context.get("repoPath") or "").strip()
    if not repo_path:
        raise HTTPException(
            status_code=400,
            detail={
                "message": (
                    "No active target repository is configured. Clone a repository first and choose an "
                    "absolute folder path outside this project repository."
                )
            },
        )
    return repo_path


def _resolve_runtime_owner_repo(runtime_context: dict) -> tuple[str | None, str | None]:
    repo_url = str(runtime_context.get("repoUrl") or "").strip()
    repo_id = str(runtime_context.get("repoId") or "").strip()

    parsed_url = parse_owner_repo_from_url(repo_url)
    if parsed_url:
        return parsed_url[0], parsed_url[1]

    if repo_id:
        try:
            owner, repo = parse_repo_owner_name(repo_id)
            return owner, repo
        except Exception:
            return None, None

    return None, None


def _build_pipeline_env(runtime_context: dict) -> dict:
    env = os.environ.copy()
    repo_path = str(runtime_context.get("repoPath") or "").strip()
    repo_id = str(runtime_context.get("repoId") or "").strip()

    if repo_path:
        env["TARGET_REPO_PATH"] = repo_path
    if repo_id:
        env["TARGET_REPO_ID"] = repo_id

    owner, repo = _resolve_runtime_owner_repo(runtime_context)
    if owner and repo:
        env["GITHUB_REPO"] = f"{owner}/{repo}"

    return env


class CloneRepoRequest(BaseModel):
    repoUrl: Optional[str] = None
    repoId: str
    ref: Optional[str] = "main"
    localStorageLocation: Optional[str] = None
    autoRunDocker: Optional[bool] = True


class BatchAnalyzeRequest(BaseModel):
    limit: Optional[int] = None
    stopOnFailure: bool = False
    maxAttempts: int = 2


def _extract_pipeline_report(logs: str) -> Optional[dict]:
    start = logs.find(PIPELINE_REPORT_START_MARKER)
    end = logs.find(PIPELINE_REPORT_END_MARKER)
    if start == -1 or end == -1 or end <= start:
        return None
    json_payload = logs[start + len(PIPELINE_REPORT_START_MARKER) : end].strip()
    if not json_payload:
        return None
    try:
        return json.loads(json_payload)
    except Exception:
        return None


def _build_jira_client() -> JiraMCPClient:
    return JiraMCPClient(
        jira_url=settings.JIRA_URL,
        email=settings.JIRA_EMAIL,
        api_token=settings.JIRA_API_TOKEN,
        project_key=settings.JIRA_PROJECT_KEY,
        excluded_ticket_keys=settings.jira_excluded_ticket_keys,
    )


def _build_github_client() -> GitHubMCPClient:
    return GitHubMCPClient(
        github_token=settings.GITHUB_TOKEN,
        mcp_server_command=settings.GITHUB_MCP_SERVER_COMMAND,
        mcp_server_args=settings.GITHUB_MCP_SERVER_ARGS,
    )


@app.get("/tickets")
def get_tickets():
    return ticket_service.fetch_tickets()


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str):
    return ticket_service.fetch_ticket(ticket_id)


@app.post("/pipeline/solve-all-bugs")
def solve_all_bugs_stream():
    """Run backend test_pipeline.py and stream logs line-by-line."""
    global _pipeline_stop_requested
    global _pipeline_stop_reason

    if _pipeline_run_state.get("status") in {"running", "stopping"}:
        raise HTTPException(status_code=409, detail={"message": "A pipeline run is already in progress"})

    backend_root = Path(__file__).resolve().parents[1]
    script_path = backend_root / "test_pipeline.py"
    if not script_path.exists():
        raise HTTPException(status_code=500, detail={"message": f"Pipeline script not found: {script_path}"})

    runtime_repo_context = _resolve_runtime_repo_context()
    _require_runtime_repo_path(runtime_repo_context)
    runtime_env = _build_pipeline_env(runtime_repo_context)

    started_at = datetime.utcnow().isoformat() + "Z"
    _pipeline_run_state.update(
        {
            "status": "running",
            "startedAt": started_at,
            "finishedAt": None,
            "exitCode": None,
            "logs": "",
            "report": None,
            "stopRequested": False,
            "stopReason": None,
            "wasStopped": False,
            "targetRepoPath": runtime_repo_context.get("repoPath"),
            "targetRepoId": runtime_repo_context.get("repoId"),
            "targetRepoUrl": runtime_repo_context.get("repoUrl"),
        }
    )

    with _pipeline_lock:
        _pipeline_stop_requested = False
        _pipeline_stop_reason = None

    def _stream():
        global _pipeline_process
        global _pipeline_stop_requested
        global _pipeline_stop_reason

        logs: list[str] = []
        return_code = 1
        process = None
        try:
            process = subprocess.Popen(
                [sys.executable, "-u", str(script_path)],
                cwd=str(backend_root),
                env=runtime_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            with _pipeline_lock:
                _pipeline_process = process
                stop_now = _pipeline_stop_requested

            if stop_now and process.poll() is None:
                process.terminate()

            if process.stdout is None:
                raise RuntimeError("Failed to open pipeline stdout stream")

            for line in process.stdout:
                logs.append(line)
                yield line

            return_code = process.wait()
        except Exception as exc:
            error_line = f"\n[Backend] Failed to run test_pipeline.py: {exc}\n"
            logs.append(error_line)
            yield error_line
        finally:
            with _pipeline_lock:
                was_stop_requested = _pipeline_stop_requested
                stop_reason = _pipeline_stop_reason
                _pipeline_process = None
                _pipeline_stop_requested = False
                _pipeline_stop_reason = None

            if was_stop_requested:
                stop_line = f"\n[SYSTEM] Pipeline stop requested: {stop_reason or 'Stopped by user'}\n"
                logs.append(stop_line)

            full_logs = "".join(logs)
            finished_at = datetime.utcnow().isoformat() + "Z"
            report = _extract_pipeline_report(full_logs)
            final_status = "stopped" if was_stop_requested else ("completed" if return_code == 0 else "failed")
            _pipeline_run_state.update(
                {
                    "status": final_status,
                    "startedAt": started_at,
                    "finishedAt": finished_at,
                    "exitCode": return_code,
                    "logs": full_logs,
                    "report": report,
                    "stopRequested": False,
                    "stopReason": stop_reason,
                    "wasStopped": was_stop_requested,
                }
            )
            if process is not None and process.poll() is None:
                process.kill()

    return StreamingResponse(_stream(), media_type="text/plain")


@app.get("/pipeline/last-run")
def get_last_pipeline_run():
    """Return latest solve-all-bugs run details including logs and parsed report."""
    return _pipeline_run_state


@app.post("/pipeline/stop")
def stop_pipeline_run():
    """Stop the currently running pipeline process."""
    global _pipeline_stop_requested
    global _pipeline_stop_reason

    with _pipeline_lock:
        if _pipeline_run_state.get("status") not in {"running", "stopping"}:
            raise HTTPException(status_code=409, detail={"message": "No running pipeline to stop"})

        _pipeline_stop_requested = True
        _pipeline_stop_reason = "Stopped by user"
        process = _pipeline_process
        _pipeline_run_state["status"] = "stopping"
        _pipeline_run_state["stopRequested"] = True
        _pipeline_run_state["stopReason"] = _pipeline_stop_reason

    if process is not None and process.poll() is None:
        try:
            process.terminate()
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    return {
        "status": "stopping",
        "message": "Pipeline stop requested",
    }


@app.post("/agent/clone-repo")
def clone_repo(request: CloneRepoRequest):
    """Clone/update a GitHub repository locally through the backend clone agent."""
    result = clone_repository_agent(request.model_dump())
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result)

    _active_repo_context.update(
        {
            "repoPath": str(result.get("localPath") or "").strip() or None,
            "repoId": str(result.get("repoId") or request.repoId or "").strip() or None,
            "repoUrl": str(result.get("repoUrl") or request.repoUrl or "").strip() or None,
            "ref": str(result.get("ref") or request.ref or "").strip() or None,
        }
    )
    _save_active_repo_context_to_disk()
    return result


@app.get("/github/repositories/{owner}/{repo}/overview")
def github_repository_overview(owner: str, repo: str):
    """Fetch repository overview through GitHub MCP (with backend fallback for resilience)."""
    try:
        client = _build_github_client()
        return client.get_repository_overview(owner=owner, repo=repo)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={"message": "Failed to load repository overview", "error": str(exc)},
        ) from exc


@app.post("/analyze/{ticket_key}")
def analyze_ticket(ticket_key: str):
    """Run full LangGraph pipeline on a single ticket."""
    jira = _build_jira_client()
    try:
        ticket = jira.get_issue(ticket_key)
    except JIRAError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "Jira issue lookup failed",
                "ticket_key": ticket_key,
                "error": exc.text or str(exc),
                "suggested_tickets": jira.search_issues(max_results=10),
            },
        ) from exc
    runtime_context = _resolve_runtime_repo_context()
    target_repo_path = _require_runtime_repo_path(runtime_context)
    return run_pipeline_with_retries(
        ticket,
        max_attempts=1,
        target_repo_path=target_repo_path,
    )


@app.post("/analyze/batch")
def analyze_tickets_batch(request: BatchAnalyzeRequest):
    """
    Pull multiple Jira tickets, but process them strictly one-by-one.
    The next ticket starts only after the current ticket fully completes.
    """

    jira = _build_jira_client()
    max_results = None if request.limit is None or request.limit <= 0 else request.limit
    tickets = jira.search_issues(max_results=max_results)

    if not tickets:
        return {
            "total_requested": 0,
            "processed": 0,
            "successful": 0,
            "halted": False,
            "halt_reason": None,
            "results": [],
            "message": "No tickets found in Jira for the configured project",
        }

    runtime_context = _resolve_runtime_repo_context()
    target_repo_path = _require_runtime_repo_path(runtime_context)
    return run_pipeline_sequential(
        tickets=tickets,
        stop_on_failure=request.stopOnFailure,
        max_attempts=max(1, min(request.maxAttempts, 5)),
        target_repo_path=target_repo_path,
    )


@app.get("/debug/retrieval/{ticket_key}")
def debug_retrieval(ticket_key: str):
    """Inspect repository retrieval without running fix/patch stages."""
    jira = _build_jira_client()
    try:
        ticket = jira.get_issue(ticket_key)
    except JIRAError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "Jira issue lookup failed",
                "ticket_key": ticket_key,
                "error": exc.text or str(exc),
                "suggested_tickets": jira.search_issues(max_results=10),
            },
        ) from exc

    runtime_context = _resolve_runtime_repo_context()
    target_repo_path = _require_runtime_repo_path(runtime_context)

    analysis = ticket_analyzer_node({"ticket": ticket})
    retrieval_state = {
        "ticket": ticket,
        "repo_id": settings.TARGET_REPO_ID,
        "commit_sha": settings.TARGET_REPO_COMMIT_SHA,
        "base_repo_path": target_repo_path,
        "repo_path": target_repo_path,
        "workspace_path": target_repo_path,
        "bug_type": analysis.get("bug_type"),
        "keywords": analysis.get("keywords"),
        "likely_files": analysis.get("likely_files"),
        "service": analysis.get("service"),
        "confidence": analysis.get("confidence"),
        "root_cause_hint": analysis.get("root_cause_hint"),
    }
    retrieval = vector_search_node(retrieval_state)

    return {
        "ticket": ticket,
        "analysis": analysis,
        "retrieval": retrieval,
    }
