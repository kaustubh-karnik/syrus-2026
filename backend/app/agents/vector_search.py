from pathlib import Path
import sys

from app.agents.state import AgentState
from app.config import settings
from app.mcp.github_client import (
    GitHubMCPClient,
    detect_local_github_repository,
    parse_repo_owner_name,
)
from app.retrieval.context_bundle import build_context_bundle
from app.retrieval.failure_interpreter import interpret_failure


def _safe_console_text(value: object) -> str:
    text = str(value)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        text.encode(encoding)
        return text
    except UnicodeEncodeError:
        return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def _log(message: object) -> None:
    print(_safe_console_text(message))


def _resolve_github_binding(repo_root: Path, commit_sha: str | None) -> dict:
    local_binding = detect_local_github_repository(repo_root)
    configured_repo = (settings.GITHUB_REPO or "").strip()

    owner = local_binding.get("owner")
    repo = local_binding.get("repo")
    source = "local_git_remote" if owner and repo else None

    if not owner or not repo:
        if configured_repo:
            try:
                owner, repo = parse_repo_owner_name(configured_repo)
                source = "settings_github_repo"
            except Exception:
                owner = None
                repo = None

    if owner and repo:
        return {
            "owner": owner,
            "repo": repo,
            "ref": (commit_sha or "").strip()
            or str(local_binding.get("commit_sha") or "").strip()
            or str(local_binding.get("branch") or "").strip()
            or settings.GITHUB_BASE_BRANCH
            or "main",
            "source": source,
            "remote_url": local_binding.get("remote_url"),
            "branch": local_binding.get("branch"),
            "commit_sha": local_binding.get("commit_sha"),
        }

    return {
        "owner": None,
        "repo": None,
        "ref": None,
        "source": None,
        "remote_url": local_binding.get("remote_url"),
        "branch": local_binding.get("branch"),
        "commit_sha": local_binding.get("commit_sha"),
    }


def _discover_mcp_signals(
    *,
    repo_root: Path,
    terms: list[str],
    likely_files: list[str],
    commit_sha: str | None,
) -> dict:
    binding = _resolve_github_binding(repo_root, commit_sha)
    if not binding.get("owner") or not binding.get("repo"):
        return {
            "binding": binding,
            "candidate_paths": [],
            "history_paths": [],
            "source": "unavailable",
        }

    _log(
        "   MCP binding : "
        f"{binding['owner']}/{binding['repo']} @ {binding['ref']} ({binding['source']})"
    )

    client = GitHubMCPClient(
        github_token=settings.GITHUB_TOKEN,
        mcp_server_command=settings.GITHUB_MCP_SERVER_COMMAND,
        mcp_server_args=settings.GITHUB_MCP_SERVER_ARGS,
    )

    try:
        candidate_result = client.discover_candidate_files(
            owner=binding["owner"],
            repo=binding["repo"],
            ref=binding["ref"],
            terms=terms,
            likely_files=likely_files,
            max_files=8,
        )
    except Exception:
        candidate_result = {"paths": []}

    try:
        history_result = client.discover_history_related_paths(
            owner=binding["owner"],
            repo=binding["repo"],
            ref=binding["ref"],
            seed_paths=[*likely_files[:4], *candidate_result.get("paths", [])[:2]],
            max_paths=8,
        )
    except Exception:
        history_result = {"paths": []}

    return {
        "binding": binding,
        "candidate_paths": candidate_result.get("paths", []),
        "history_paths": history_result.get("paths", []),
        "source": "github_mcp",
    }


def vector_search_node(state: AgentState) -> AgentState:
    repo_path = str(state.get("repo_path") or "").strip()
    if not repo_path:
        return {
            "retrieval_context": None,
            "retrieved_files": [],
            "retrieved_code": "",
            "status": "failed",
            "error": "Target repository path is missing in state",
        }

    repo_root = Path(repo_path).resolve()
    if not repo_root.exists():
        return {
            "retrieval_context": None,
            "retrieved_files": [],
            "retrieved_code": "",
            "status": "failed",
            "error": f"Target repository path does not exist: {repo_root}",
        }

    failure_signals = interpret_failure(
        state.get("ticket") or {},
        retry_feedback=state.get("retry_feedback"),
        repo_root=repo_root,
        repo_state=state.get("repo_state"),
    )

    terms: list[str] = []
    if state.get("keywords"):
        terms.extend(str(item) for item in (state.get("keywords") or []) if item)
    if state.get("bug_type"):
        terms.append(str(state["bug_type"]))
    if state.get("root_cause_hint"):
        terms.append(str(state["root_cause_hint"]))
    if state.get("service"):
        terms.append(str(state["service"]))

    retry_context = state.get("retry_context")
    failed_edit = (retry_context or {}).get("failed_edit") or {}
    if failed_edit.get("requested_file"):
        terms.append(str(failed_edit.get("requested_file")))

    for item in [
        failure_signals.get("error_type"),
        failure_signals.get("endpoint"),
        failure_signals.get("expected_behavior"),
        *(failure_signals.get("suspect_symbols") or []),
    ]:
        if item:
            terms.append(str(item))

    likely_files = [str(item) for item in (state.get("likely_files") or []) if item]

    _log("\nRepository Retrieval: assembling grounded file pack...")
    _log(f"   Repo        : {repo_root}")
    _log(f"   Terms       : {terms}")
    _log(f"   Likely      : {likely_files}")

    mcp_signals = _discover_mcp_signals(
        repo_root=repo_root,
        terms=terms,
        likely_files=likely_files,
        commit_sha=state.get("commit_sha"),
    )
    if mcp_signals.get("candidate_paths"):
        _log(f"   MCP paths   : {mcp_signals.get('candidate_paths')[:6]}")
    if mcp_signals.get("history_paths"):
        _log(f"   MCP history : {mcp_signals.get('history_paths')[:6]}")

    retrieval_context = build_context_bundle(
        repo_root=repo_root,
        ticket=state.get("ticket") or {},
        terms=terms,
        likely_files=likely_files,
        service=state.get("service"),
        bug_type=state.get("bug_type"),
        root_cause_hint=state.get("root_cause_hint"),
        failure_signals=failure_signals,
        retry_context=retry_context,
        requested_commit_sha=state.get("commit_sha"),
        mcp_candidate_paths=mcp_signals.get("candidate_paths", []),
        mcp_history_paths=mcp_signals.get("history_paths", []),
        github_binding=mcp_signals.get("binding"),
    )

    files = retrieval_context.get("ranked_files", [])
    if not files:
        return {
            "retrieval_context": retrieval_context,
            "retrieved_files": [],
            "retrieved_code": "",
            "status": "no_results",
            "error": "No relevant files found in the local target repository",
        }

    validation_context = retrieval_context.get("validation_context") or {}
    validation_plan = retrieval_context.get("validation_plan") or {}
    repo_state = retrieval_context.get("repo_state") or {}
    repo_profile = retrieval_context.get("repo_profile") or {}

    if validation_plan.get("selected_test_paths") or validation_context.get("selected_test_paths"):
        _log(
            "   Test pack   : "
            f"{validation_plan.get('selected_test_paths') or validation_context.get('selected_test_paths')}"
        )
    if repo_state.get("commit_sha"):
        _log(
            "   Repo state  : "
            f"branch={repo_state.get('branch')} commit={repo_state.get('commit_sha')}"
        )
    if repo_profile.get("primary_service"):
        _log(f"   Profile     : {repo_profile.get('primary_service')}")
    coverage = retrieval_context.get("evidence_coverage") or {}
    if coverage:
        _log(
            "   Evidence    : "
            f"score={coverage.get('score')} stack={coverage.get('top_stack_frame_included')} "
            f"tests={coverage.get('validation_targets_included')} symbols={coverage.get('suspect_symbol_included')}"
        )

    return {
        "retrieval_context": retrieval_context,
        "failure_signals": failure_signals,
        "retrieved_files": files,
        "retrieved_code": retrieval_context.get("context_text", ""),
        "validation_context": validation_context,
        "validation_plan": validation_plan,
        "repo_state": repo_state,
        "repo_profile": repo_profile,
        "symbol_graph_summary": retrieval_context.get("symbol_graph_summary"),
        "remote_signals": retrieval_context.get("remote_signals"),
        "status": "code_retrieved",
        "error": None,
    }
