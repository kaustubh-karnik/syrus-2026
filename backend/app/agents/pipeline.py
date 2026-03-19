from pathlib import Path

from langgraph.graph import END, StateGraph

from app.agents.fix_generator import fix_generator_node
from app.agents.patch_code import patch_code_node
from app.agents.create_pr import create_pr_node
from app.agents.sandbox_runner import sandbox_runner_node
from app.agents.state import AgentState
from app.agents.ticket_analyzer import ticket_analyzer_node
from app.agents.vector_search import vector_search_node
from app.agents.workspace_manager import (
    cleanup_attempt_workspace,
    create_attempt_workspace,
    promote_workspace_changes,
)
from app.config import settings


SUCCESS_TERMINAL_STATUSES = {"sandbox_passed"}
DEFAULT_MAX_FIX_ATTEMPTS = 2
NON_RETRYABLE_CATEGORIES = {"infra"}
MAX_RETRY_FILE_CONTEXT_CHARS = 50000


def should_continue(state: AgentState) -> str:
    if state.get("status") == "failed":
        return "end"
    return "search_code"


def should_patch(state: AgentState) -> str:
    if state.get("status") == "fix_failed" or not state.get("fix"):
        return "end"
    return "patch_code"


def should_sandbox(state: AgentState) -> str:
    patch_result = state.get("patch_result") or {}
    if state.get("status") != "patched" or not patch_result.get("success"):
        return "end"
    return "sandbox_runner"


def build_pipeline() -> StateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("analyze_ticket", ticket_analyzer_node)
    graph.add_node("search_code", vector_search_node)
    graph.add_node("generate_fix", fix_generator_node)
    graph.add_node("patch_code", patch_code_node)
    graph.add_node("sandbox_runner", sandbox_runner_node)
    graph.set_entry_point("analyze_ticket")
    graph.add_conditional_edges("analyze_ticket", should_continue, {"search_code": "search_code", "end": END})
    graph.add_edge("search_code", "generate_fix")
    graph.add_conditional_edges("generate_fix", should_patch, {"patch_code": "patch_code", "end": END})
    graph.add_conditional_edges("patch_code", should_sandbox, {"sandbox_runner": "sandbox_runner", "end": END})
    graph.add_edge("sandbox_runner", END)
    return graph.compile()


def run_pipeline(
    ticket: dict,
    *,
    retry_feedback: str | None = None,
    fix_attempt: int = 1,
    base_repo_path: str | None = None,
    repo_path: str | None = None,
    workspace_path: str | None = None,
    retry_context: dict | None = None,
) -> dict:
    pipeline = build_pipeline()
    base_repo = base_repo_path or settings.TARGET_REPO_PATH
    attempt_repo = repo_path or base_repo

    initial_state: AgentState = {
        "ticket": ticket,
        "repo_id": settings.TARGET_REPO_ID,
        "commit_sha": settings.TARGET_REPO_COMMIT_SHA,
        "base_repo_path": base_repo,
        "repo_path": attempt_repo,
        "workspace_path": workspace_path or attempt_repo,
        "bug_type": None,
        "keywords": None,
        "likely_files": None,
        "service": None,
        "confidence": None,
        "root_cause_hint": None,
        "failure_signals": None,
        "retrieval_context": None,
        "retrieved_files": None,
        "retrieved_code": None,
        "validation_context": None,
        "validation_plan": None,
        "repo_state": None,
        "repo_profile": None,
        "symbol_graph_summary": None,
        "remote_signals": None,
        "fix": None,
        "patch_result": None,
        "sandbox_result": None,
        "promotion_result": None,
        "retry_feedback": retry_feedback,
        "retry_context": retry_context,
        "fix_attempt": fix_attempt,
        "retry_category": None,
        "error": None,
        "status": "starting",
    }

    return pipeline.invoke(initial_state)


def _extract_retry_feedback(state: dict, attempt: int) -> str:
    fix = state.get("fix") or {}
    patch_result = state.get("patch_result") or {}
    sandbox_result = state.get("sandbox_result") or {}

    lines = [
        f"Attempt {attempt} failed.",
        f"Final status: {state.get('status', 'unknown')}",
        f"Retry category: {state.get('retry_category', 'unknown')}",
    ]

    if state.get("error"):
        lines.append(f"State error: {state.get('error')}")

    if fix:
        lines.append(
            "Fix output: "
            f"file={fix.get('primary_file') or fix.get('file')} confidence={fix.get('confidence')} "
            f"edits={len(fix.get('edits') or [])} reason={fix.get('reason')}"
        )

    if patch_result:
        lines.append(
            "Patch output: "
            f"status={patch_result.get('status')} success={patch_result.get('success')} "
            f"error={patch_result.get('error')} reason={patch_result.get('reason')}"
        )
        if patch_result.get("edit_results"):
            lines.append(f"Applied edit summary: {patch_result.get('edit_results')}")
        if patch_result.get("anchor_diagnostics"):
            lines.append(f"Anchor diagnostics: {patch_result.get('anchor_diagnostics')}")

    retrieval_context = state.get("retrieval_context") or {}
    if retrieval_context.get("validation_context"):
        lines.append(f"Retrieval validation context: {retrieval_context.get('validation_context')}")
    if retrieval_context.get("validation_plan"):
        lines.append(f"Retrieval validation plan: {retrieval_context.get('validation_plan')}")
    if retrieval_context.get("repo_profile"):
        lines.append(f"Repo profile summary: {retrieval_context.get('repo_profile')}")

    if sandbox_result:
        lines.append(
            "Sandbox output: "
            f"success={sandbox_result.get('success')} stage={sandbox_result.get('stage')} "
            f"error={sandbox_result.get('error')}"
        )
        if sandbox_result.get("compile_failure_context"):
            lines.append(f"Compile failure context: {sandbox_result.get('compile_failure_context')}")
        if sandbox_result.get("test_plan_source"):
            lines.append(f"Test plan source: {sandbox_result.get('test_plan_source')}")
        if sandbox_result.get("selected_tests"):
            lines.append(f"Selected tests: {sandbox_result.get('selected_tests')}")
        if sandbox_result.get("failed_tests"):
            lines.append(f"Failed tests: {sandbox_result.get('failed_tests')}")
        if sandbox_result.get("failure_reason"):
            lines.append(f"Failure reason:\n{str(sandbox_result.get('failure_reason'))[-1200:]}")
        if sandbox_result.get("build_output"):
            lines.append(f"Sandbox build output tail:\n{str(sandbox_result.get('build_output'))[-1200:]}")
        if sandbox_result.get("test_output"):
            lines.append(f"Sandbox test output tail:\n{str(sandbox_result.get('test_output'))[-1200:]}")
        if sandbox_result.get("test_error"):
            lines.append(f"Sandbox test stderr tail:\n{str(sandbox_result.get('test_error'))[-800:]}")

    lines.append(
        "Generate a corrected structured edit plan. Re-anchor every edit against the exact local file content "
        "and include all required files such as tests or migrations."
    )
    feedback = "\n".join(lines)
    return feedback[-8000:]


def _should_retry(state: dict) -> bool:
    if state.get("status") in SUCCESS_TERMINAL_STATUSES:
        return False
    retry_category = str(state.get("retry_category") or "").strip().lower()
    return retry_category not in NON_RETRYABLE_CATEGORIES


def _read_retry_file_context(base_repo_path: str, rel_path: str) -> dict | None:
    if not rel_path:
        return None
    repo_root = Path(base_repo_path).resolve()
    candidate = (repo_root / rel_path).resolve()
    if not str(candidate).startswith(str(repo_root)) or not candidate.exists() or not candidate.is_file():
        return None
    try:
        content = candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return {
        "path": rel_path,
        "content": content[:MAX_RETRY_FILE_CONTEXT_CHARS],
    }


def _retry_neighbor_paths(failed_edit: dict, retrieval_context: dict | None) -> list[str]:
    if not retrieval_context:
        return []

    target_path = str(
        failed_edit.get("resolved_file")
        or failed_edit.get("requested_file")
        or ""
    ).replace("\\", "/").strip()
    target_parent = Path(target_path).parent if target_path else None

    neighbors: list[str] = []
    for item in retrieval_context.get("grounded_files") or retrieval_context.get("ranked_files") or []:
        rel_path = str(item.get("path") or "").replace("\\", "/").strip()
        if not rel_path or rel_path == target_path:
            continue
        if target_parent and Path(rel_path).parent == target_parent:
            neighbors.append(rel_path)
        elif "same_directory_sibling" in (item.get("relation_reasons") or []):
            neighbors.append(rel_path)
        if len(neighbors) >= 2:
            break
    return neighbors


def _build_retry_context(base_repo_path: str, state: dict) -> dict | None:
    if str(state.get("retry_category") or "").strip().lower() != "reanchor":
        return None

    patch_result = state.get("patch_result") or {}
    fix = state.get("fix") or {}
    retrieval_context = state.get("retrieval_context") or {}
    failed_edit = patch_result.get("failed_edit") or {}
    candidate_paths: list[str] = []

    for path in [
        failed_edit.get("resolved_file"),
        failed_edit.get("requested_file"),
        patch_result.get("file"),
        *(retrieval_context.get("validation_plan", {}).get("selected_test_paths") or []),
        *(retrieval_context.get("validation_context", {}).get("selected_test_paths") or []),
        *_retry_neighbor_paths(failed_edit, retrieval_context),
        *(item.get("file") for item in (patch_result.get("anchor_diagnostics") or [])),
    ]:
        rel_path = str(path or "").replace("\\", "/").strip()
        if rel_path and rel_path not in candidate_paths:
            candidate_paths.append(rel_path)

    candidate_files = []
    for rel_path in candidate_paths[:4]:
        file_context = _read_retry_file_context(base_repo_path, rel_path)
        if file_context:
            candidate_files.append(file_context)

    if not candidate_files and not failed_edit:
        return None

    return {
        "mode": "reanchor",
        "failed_edit": failed_edit,
        "candidate_files": candidate_files,
        "previous_fix_reason": fix.get("reason"),
        "previous_fix_confidence": fix.get("confidence"),
        "anchor_diagnostics": patch_result.get("anchor_diagnostics") or [],
        "validation_context": retrieval_context.get("validation_context"),
        "validation_plan": retrieval_context.get("validation_plan"),
        "repo_profile": retrieval_context.get("repo_profile"),
    }


def run_pipeline_with_retries(
    ticket: dict,
    *,
    max_attempts: int = DEFAULT_MAX_FIX_ATTEMPTS,
    initial_retry_feedback: str | None = None,
    target_repo_path: str | None = None,
) -> dict:
    attempts = max(DEFAULT_MAX_FIX_ATTEMPTS, int(max_attempts or DEFAULT_MAX_FIX_ATTEMPTS))
    attempt_states: list[dict] = []
    retry_feedback = initial_retry_feedback
    retry_context = None
    final_state: dict = {}
    preserved_workspaces: list[str] = []
    ticket_key = ticket.get("jira_key", "UNKNOWN")
    base_target_repo = target_repo_path or settings.TARGET_REPO_PATH

    last_workspace_info: dict | None = None

    for attempt in range(1, attempts + 1):
        print(f"\nPipeline attempt {attempt}/{attempts}")
        workspace_info = create_attempt_workspace(base_target_repo, ticket_key, attempt)
        last_workspace_info = workspace_info
        final_state = run_pipeline(
            ticket,
            retry_feedback=retry_feedback,
            fix_attempt=attempt,
            base_repo_path=workspace_info["base_repo_path"],
            repo_path=workspace_info["workspace_path"],
            workspace_path=workspace_info["workspace_path"],
            retry_context=retry_context,
        )

        if final_state.get("status") in SUCCESS_TERMINAL_STATUSES:
            patch_result = final_state.get("patch_result") or {}
            promotion_result = promote_workspace_changes(
                workspace_info["base_repo_path"],
                workspace_info["workspace_path"],
                patch_result.get("modified_files", []),
                ticket_key,
            )
            final_state = dict(final_state)
            final_state["promotion_result"] = promotion_result
            if not promotion_result.get("success"):
                final_state["status"] = "promotion_failed"
                final_state["error"] = "Failed to promote validated patch back to target repository"
                final_state["retry_category"] = "infra"
            else:
                pr_state = create_pr_node(
                    {
                        **final_state,
                        "base_repo_path": workspace_info["base_repo_path"],
                        "repo_path": workspace_info["base_repo_path"],
                    }
                )
                final_state["pr_result"] = pr_state.get("pr_result")
                final_state["pr_status"] = pr_state.get("status")
                final_state["pr_error"] = pr_state.get("error")

        attempt_states.append(final_state)

        is_success = final_state.get("status") in SUCCESS_TERMINAL_STATUSES
        can_retry = attempt < attempts and _should_retry(final_state)

        if is_success or can_retry:
            cleanup_attempt_workspace(workspace_info["workspace_path"])
        else:
            preserved_path = workspace_info["workspace_path"]
            preserved_workspaces.append(preserved_path)
            final_state = dict(final_state)
            final_state["preserved_workspace_path"] = preserved_path
            print(f"Preserving failed attempt workspace for inspection: {preserved_path}")

        if is_success:
            break
        if can_retry:
            retry_feedback = _extract_retry_feedback(final_state, attempt)
            retry_context = _build_retry_context(base_target_repo, final_state)
            continue
        break

    final_state = dict(final_state)

    # If final attempt did not pass sandbox but produced a patch, promote and create PR anyway.
    final_patch_result = final_state.get("patch_result") or {}
    has_final_patch = bool(final_patch_result.get("success"))
    has_promotion = bool((final_state.get("promotion_result") or {}).get("success"))
    final_status = str(final_state.get("status") or "")

    if (
        has_final_patch
        and not has_promotion
        and final_status not in SUCCESS_TERMINAL_STATUSES
        and last_workspace_info is not None
    ):
        try:
            promotion_result = promote_workspace_changes(
                last_workspace_info["base_repo_path"],
                last_workspace_info["workspace_path"],
                final_patch_result.get("modified_files", []),
                ticket_key,
            )
            final_state["promotion_result"] = promotion_result
            if promotion_result.get("success"):
                pr_state = create_pr_node(
                    {
                        **final_state,
                        "base_repo_path": last_workspace_info["base_repo_path"],
                        "repo_path": last_workspace_info["base_repo_path"],
                    }
                )
                final_state["pr_result"] = pr_state.get("pr_result")
                final_state["pr_status"] = pr_state.get("status")
                final_state["pr_error"] = pr_state.get("error")
            else:
                final_state["pr_status"] = "pr_failed"
                final_state["pr_error"] = "Patch promotion failed before PR creation"
        except Exception as exc:
            final_state["pr_status"] = "pr_failed"
            final_state["pr_error"] = f"Post-failure PR flow failed: {exc}"

    if preserved_workspaces:
        final_state["preserved_workspaces"] = preserved_workspaces
    final_state["attempt_count"] = len(attempt_states)
    final_state["attempts"] = [
        {
            "attempt": idx,
            "status": state.get("status"),
            "error": state.get("error"),
            "retry_category": state.get("retry_category"),
            "patch_result": state.get("patch_result"),
            "sandbox_result": state.get("sandbox_result"),
            "promotion_result": state.get("promotion_result"),
            "pr_result": state.get("pr_result"),
            "pr_status": state.get("pr_status"),
            "pr_error": state.get("pr_error"),
            "preserved_workspace_path": state.get("preserved_workspace_path"),
        }
        for idx, state in enumerate(attempt_states, start=1)
    ]
    return final_state


def run_pipeline_sequential(
    tickets: list[dict],
    *,
    stop_on_failure: bool = False,
    max_attempts: int = DEFAULT_MAX_FIX_ATTEMPTS,
    target_repo_path: str | None = None,
) -> dict:
    queue = [ticket for ticket in (tickets or []) if isinstance(ticket, dict)]
    results: list[dict] = []
    halted = False
    halt_reason = None

    def _build_post_batch_llm_feedback(sandbox_result: dict) -> str:
        lines = [
            "Post-batch docker full-suite validation failed.",
            f"Error: {sandbox_result.get('error')}",
            f"Failed tests: {sandbox_result.get('failed_tests')}",
        ]
        if sandbox_result.get("failure_reason"):
            lines.append(f"Failure reason:\n{str(sandbox_result.get('failure_reason'))[-1600:]}")
        if sandbox_result.get("test_output"):
            lines.append(f"Docker test output tail:\n{str(sandbox_result.get('test_output'))[-3000:]}")
        if sandbox_result.get("test_error"):
            lines.append(f"Docker stderr tail:\n{str(sandbox_result.get('test_error'))[-2000:]}")
        return "\n".join(lines)

    for index, ticket in enumerate(queue, start=1):
        ticket_key = ticket.get("jira_key", f"TICKET-{index}")
        print(f"\n[{index}/{len(queue)}] Starting ticket: {ticket_key}")

        state = run_pipeline_with_retries(
            ticket,
            max_attempts=max_attempts,
            target_repo_path=target_repo_path,
        )
        final_status = state.get("status", "unknown")
        success = final_status in SUCCESS_TERMINAL_STATUSES

        results.append(
            {
                "ticket_key": ticket_key,
                "status": final_status,
                "success": success,
                "error": state.get("error"),
                "result": state,
                "attempt_count": state.get("attempt_count", 1),
            }
        )

        if not success and stop_on_failure:
            halted = True
            halt_reason = (
                f"Ticket {ticket_key} ended with status '{final_status}'. "
                "Sequential processing halted before starting the next ticket."
            )
            print(f"Stop: {halt_reason}")
            break

    response = {
        "total_requested": len(queue),
        "processed": len(results),
        "successful": sum(1 for item in results if item["success"]),
        "halted": halted,
        "halt_reason": halt_reason,
        "results": results,
    }

    all_incidents_compiled = bool(results) and all(item.get("success") for item in results)
    if settings.SANDBOX_RUN_DOCKER_FULL_SUITE_AFTER_BATCH and all_incidents_compiled:
        print("\nRunning post-batch docker full-suite validation...")
        aggregate_modified_files: list[str] = []
        for item in results:
            patch = (item.get("result") or {}).get("patch_result") or {}
            for rel_path in patch.get("modified_files") or []:
                normalized = str(rel_path or "").replace("\\", "/").strip()
                if normalized and normalized not in aggregate_modified_files:
                    aggregate_modified_files.append(normalized)

        last_state = (results[-1].get("result") or {}) if results else {}
        post_state = {
            "ticket": {"jira_key": "POST-BATCH-VALIDATION"},
            "patch_result": {
                "success": True,
                "modified_files": aggregate_modified_files,
            },
            "retrieval_context": last_state.get("retrieval_context"),
            "repo_state": last_state.get("repo_state"),
            "repo_profile": last_state.get("repo_profile"),
            "service": "python-service",
            "force_docker_full_suite": True,
        }
        post_validation = sandbox_runner_node(post_state)
        sandbox_result = post_validation.get("sandbox_result") or {}
        post_validation_payload = {
            "status": post_validation.get("status"),
            "success": bool(sandbox_result.get("success")),
            "error": post_validation.get("error") or sandbox_result.get("error"),
            "sandbox_result": sandbox_result,
        }
        if not sandbox_result.get("success"):
            post_validation_payload["llm_feedback"] = _build_post_batch_llm_feedback(sandbox_result)
        response["post_batch_validation"] = post_validation_payload

        if (
            not sandbox_result.get("success")
            and settings.SANDBOX_AUTO_REPAIR_AFTER_POST_BATCH_FAILURE
            and queue
        ):
            print("\nPost-batch validation failed. Running one automatic LLM repair cycle...")
            auto_feedback = post_validation_payload.get("llm_feedback") or "Post-batch docker full-suite validation failed."
            auto_max_attempts = max(1, int(settings.SANDBOX_AUTO_REPAIR_MAX_ATTEMPTS or 1))
            auto_results: list[dict] = []

            for index, ticket in enumerate(queue, start=1):
                ticket_key = ticket.get("jira_key", f"TICKET-{index}")
                print(f"[auto-repair {index}/{len(queue)}] Retrying ticket: {ticket_key}")
                auto_state = run_pipeline_with_retries(
                    ticket,
                    max_attempts=auto_max_attempts,
                    initial_retry_feedback=auto_feedback,
                )
                auto_status = auto_state.get("status", "unknown")
                auto_success = auto_status in SUCCESS_TERMINAL_STATUSES
                auto_results.append(
                    {
                        "ticket_key": ticket_key,
                        "status": auto_status,
                        "success": auto_success,
                        "error": auto_state.get("error"),
                        "attempt_count": auto_state.get("attempt_count", 1),
                        "result": auto_state,
                    }
                )

            response["post_batch_auto_repair"] = {
                "enabled": True,
                "feedback_source": "post_batch_validation.llm_feedback",
                "max_attempts_per_ticket": auto_max_attempts,
                "processed": len(auto_results),
                "successful": sum(1 for item in auto_results if item.get("success")),
                "results": auto_results,
            }

    return response


if __name__ == "__main__":
    import json

    from app.mcp.jira_client import JiraMCPClient

    client = JiraMCPClient(
        jira_url=settings.JIRA_URL,
        email=settings.JIRA_EMAIL,
        api_token=settings.JIRA_API_TOKEN,
        project_key=settings.JIRA_PROJECT_KEY,
    )

    tickets = client.search_issues(max_results=1)
    if tickets:
        ticket = tickets[0]
        print(f"\nRunning pipeline on: {ticket['jira_key']}\n")
        result = run_pipeline_with_retries(ticket, max_attempts=1)
        print("\n=== FINAL STATE ===")
        print(json.dumps({k: v for k, v in result.items() if k != "ticket"}, indent=2))
    else:
        print("No tickets found")
