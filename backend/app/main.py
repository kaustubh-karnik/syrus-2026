import json
import subprocess
import sys
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
from app.config import settings
from app.mcp.github_client import GitHubMCPClient
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
}


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
    if _pipeline_run_state.get("status") == "running":
        raise HTTPException(status_code=409, detail={"message": "A pipeline run is already in progress"})

    backend_root = Path(__file__).resolve().parents[1]
    script_path = backend_root / "test_pipeline.py"
    if not script_path.exists():
        raise HTTPException(status_code=500, detail={"message": f"Pipeline script not found: {script_path}"})

    started_at = datetime.utcnow().isoformat() + "Z"
    _pipeline_run_state.update(
        {
            "status": "running",
            "startedAt": started_at,
            "finishedAt": None,
            "exitCode": None,
            "logs": "",
            "report": None,
        }
    )

    def _stream():
        logs: list[str] = []
        return_code = 1
        process = None
        try:
            process = subprocess.Popen(
                [sys.executable, "-u", str(script_path)],
                cwd=str(backend_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
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
            full_logs = "".join(logs)
            finished_at = datetime.utcnow().isoformat() + "Z"
            report = _extract_pipeline_report(full_logs)
            _pipeline_run_state.update(
                {
                    "status": "completed" if return_code == 0 else "failed",
                    "startedAt": started_at,
                    "finishedAt": finished_at,
                    "exitCode": return_code,
                    "logs": full_logs,
                    "report": report,
                }
            )
            if process is not None and process.poll() is None:
                process.kill()

    return StreamingResponse(_stream(), media_type="text/plain")


@app.get("/pipeline/last-run")
def get_last_pipeline_run():
    """Return latest solve-all-bugs run details including logs and parsed report."""
    return _pipeline_run_state


@app.post("/agent/clone-repo")
def clone_repo(request: CloneRepoRequest):
    """Clone/update a GitHub repository locally through the backend clone agent."""
    result = clone_repository_agent(request.model_dump())
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result)
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
    return run_pipeline_with_retries(ticket, max_attempts=1)


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

    return run_pipeline_sequential(
        tickets=tickets,
        stop_on_failure=request.stopOnFailure,
        max_attempts=max(1, min(request.maxAttempts, 5)),
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

    analysis = ticket_analyzer_node({"ticket": ticket})
    retrieval_state = {
        "ticket": ticket,
        "repo_id": settings.TARGET_REPO_ID,
        "commit_sha": settings.TARGET_REPO_COMMIT_SHA,
        "base_repo_path": settings.TARGET_REPO_PATH,
        "repo_path": settings.TARGET_REPO_PATH,
        "workspace_path": settings.TARGET_REPO_PATH,
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
