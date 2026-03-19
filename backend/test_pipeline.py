import sys
import os
import json
from pathlib import Path

sys.path.append(".")

from app.config import settings
from app.mcp.jira_client import JiraMCPClient
from app.agents.pipeline import run_pipeline_sequential


REPORT_START_MARKER = "PIPELINE_REPORT_JSON_START"
REPORT_END_MARKER = "PIPELINE_REPORT_JSON_END"


def _absolute_paths(repo_root: Path, rel_paths: list[str] | None) -> list[str]:
    output: list[str] = []
    for rel_path in rel_paths or []:
        normalized = str(rel_path or "").replace("\\", "/").strip()
        if not normalized:
            continue
        output.append(str((repo_root / normalized).resolve()))
    return output


def _build_detailed_report(batch_result: dict, target_repo_root: Path) -> dict:
    ticket_reports: list[dict] = []
    for item in batch_result.get("results", []):
        state = item.get("result") or {}
        patch = state.get("patch_result") or {}
        promotion = state.get("promotion_result") or {}
        sandbox = state.get("sandbox_result") or {}
        pr_result = state.get("pr_result") or {}

        ticket_reports.append(
            {
                "ticket_key": item.get("ticket_key"),
                "status": item.get("status"),
                "success": bool(item.get("success")),
                "attempt_count": item.get("attempt_count", 1),
                "error": item.get("error"),
                "edit_reason": patch.get("reason"),
                "edited_files": _absolute_paths(target_repo_root, patch.get("modified_files") or []),
                "promoted_files": _absolute_paths(target_repo_root, promotion.get("promoted_files") or []),
                "edit_details": [
                    {
                        "index": edit.get("index"),
                        "requested_file": edit.get("requested_file"),
                        "resolved_file": str((target_repo_root / str(edit.get("resolved_file") or "")).resolve())
                        if edit.get("resolved_file")
                        else None,
                        "operation": edit.get("operation"),
                        "strategy": edit.get("strategy"),
                    }
                    for edit in (patch.get("edit_results") or [])
                ],
                "where_was_edited": patch.get("diff_paths") or [],
                "tests": {
                    "passed": bool(sandbox.get("success")),
                    "selected_tests": sandbox.get("selected_tests") or [],
                    "failed_tests": sandbox.get("failed_tests") or [],
                    "test_plan_source": sandbox.get("test_plan_source"),
                    "failure_reason": sandbox.get("failure_reason") or sandbox.get("error"),
                },
                "pr": {
                    "status": state.get("pr_status"),
                    "url": pr_result.get("pr_url"),
                    "error": state.get("pr_error"),
                },
            }
        )

    summary = {
        "requested": batch_result.get("total_requested", 0),
        "processed": batch_result.get("processed", 0),
        "successful": batch_result.get("successful", 0),
        "halted": bool(batch_result.get("halted")),
        "halt_reason": batch_result.get("halt_reason"),
    }

    return {
        "summary": summary,
        "tickets": ticket_reports,
        "post_batch_validation": batch_result.get("post_batch_validation") or {},
        "post_batch_auto_repair": batch_result.get("post_batch_auto_repair") or {},
    }


def _ticket_override_from_inputs() -> str | None:
    # Priority: CLI argument over environment variable
    if len(sys.argv) > 1 and str(sys.argv[1]).strip():
        return str(sys.argv[1]).strip()
    env_value = os.getenv("JIRA_TEST_TICKET_KEY", "").strip()
    return env_value or None


def run_test():
    print("\n" + "=" * 60)
    print("  FULL PIPELINE TEST: JIRA -> ANALYSIS -> VECTOR SEARCH -> FIX -> PATCH")
    print("=" * 60)
    target_repo_root = Path(settings.TARGET_REPO_PATH).resolve()
    print(f"Target repo root (where promoted changes are written): {target_repo_root}")

    print("\nStep 1: Connecting to Jira MCP...")
    try:
        jira = JiraMCPClient(
            jira_url=settings.JIRA_URL,
            email=settings.JIRA_EMAIL,
            api_token=settings.JIRA_API_TOKEN,
            project_key=settings.JIRA_PROJECT_KEY,
            excluded_ticket_keys=settings.jira_excluded_ticket_keys,
        )
    except Exception as exc:
        print(f"Failed to connect to Jira: {exc}")
        return

    if settings.jira_excluded_ticket_keys:
        print(f"Ignoring Jira tickets: {settings.jira_excluded_ticket_keys}")

    ticket_override = _ticket_override_from_inputs()

    print("\nStep 2: Fetching tickets from Jira...")
    try:
        tickets = jira.search_issues(max_results=None)
    except Exception as exc:
        print(f"Failed to fetch tickets: {exc}")
        return

    if not tickets:
        print("No tickets found. Create some tickets in your Jira project first.")
        return

    print(f"Found {len(tickets)} ticket(s)\n")
    for ticket in tickets:
        print(f"   {ticket['jira_key']} | {ticket['priority']} | {ticket['summary'][:60]}")

    if ticket_override:
        print(f"\nSingle-ticket test override enabled: {ticket_override}")
        filtered = [item for item in tickets if str(item.get("jira_key", "")).strip().upper() == ticket_override.upper()]
        if not filtered:
            print("   Ticket not in fetched list, trying direct Jira lookup...")
            try:
                direct = jira.get_issue(ticket_override)
                filtered = [direct]
            except Exception as exc:
                print(f"   Could not resolve ticket {ticket_override}: {exc}")
                return
        tickets = filtered
        print(f"   Running only: {[item.get('jira_key') for item in tickets]}")

    print("\nStep 3: Running sequential pipeline (continue after failed tickets)...\n")
    print("-" * 80)

    batch_result = run_pipeline_sequential(
        tickets=tickets,
        stop_on_failure=False,
        max_attempts=2,
    )

    detailed_report = _build_detailed_report(batch_result, target_repo_root)

    for item in batch_result.get("results", []):
        result = item.get("result", {})
        print(f"\nProcessed Ticket: {item.get('ticket_key', 'UNKNOWN')}")
        print(f"   Final Status: {item.get('status', 'unknown')}")
        print(f"   Attempts Used: {item.get('attempt_count', 1)}")
        if item.get("error"):
            print(f"   Error: {item['error']}")

        patch = result.get("patch_result") or {}
        if patch:
            print(f"   Patch Status: {patch.get('status', 'N/A')} | File: {patch.get('file', 'N/A')}")
            patch_summary = patch.get("summary") or {}
            if patch_summary:
                print(
                    "   Patch Summary: "
                    f"applied_files={patch_summary.get('applied_files', 0)} "
                    f"skipped_edits={patch_summary.get('skipped_edits', 0)} "
                    f"no_op_edits={patch_summary.get('no_op_edits', 0)}"
                )
            workspace_path = patch.get("workspace_path") or result.get("workspace_path")
            if workspace_path:
                print(f"   Attempt workspace: {workspace_path}")

            modified_files = patch.get("modified_files") or []
            if modified_files:
                print("   Modified files (absolute paths):")
                for rel_path in modified_files:
                    abs_path = target_repo_root / str(rel_path).replace("\\", "/")
                    print(f"      {abs_path}")

            diff_paths = patch.get("diff_paths") or []
            if diff_paths:
                print("   Workspace diff artifacts:")
                for diff_path in diff_paths:
                    print(f"      {diff_path}")

            skipped_edits = patch.get("skipped_edits") or []
            if skipped_edits:
                print("   Skipped edits:")
                for entry in skipped_edits[:8]:
                    print(
                        "      "
                        f"edit#{entry.get('index')} file={entry.get('resolved_file') or entry.get('requested_file')} "
                        f"reason={entry.get('reason')}"
                    )

            no_op_entries = [entry for entry in (patch.get("edit_results") or []) if entry.get("noop")]
            if no_op_entries:
                print("   No-op edits:")
                for entry in no_op_entries[:8]:
                    print(
                        "      "
                        f"edit#{entry.get('index')} file={entry.get('resolved_file')} "
                        f"reason={entry.get('noop_reason')}"
                    )

        promotion = result.get("promotion_result") or {}
        if promotion:
            promoted_files = promotion.get("promoted_files") or []
            if promoted_files:
                print("   Promoted files in target repo (absolute paths):")
                for rel_path in promoted_files:
                    abs_path = target_repo_root / str(rel_path).replace("\\", "/")
                    print(f"      {abs_path}")
            promotion_diffs = promotion.get("diff_paths") or []
            if promotion_diffs:
                print("   Target repo backup diffs:")
                for diff_path in promotion_diffs:
                    print(f"      {diff_path}")

        preserved_workspace = result.get("preserved_workspace_path")
        if preserved_workspace:
            print(f"   Preserved failed workspace: {preserved_workspace}")

        sandbox = result.get("sandbox_result") or {}
        if sandbox:
            print(f"   Sandbox: {'PASSED' if sandbox.get('success') else 'FAILED'}")
            if sandbox.get("test_plan_source"):
                print(f"   Test Plan Source: {sandbox.get('test_plan_source')}")
            if sandbox.get("selected_tests"):
                print(f"   Tests Run: {sandbox.get('selected_tests')}")
            if sandbox.get("failed_tests"):
                print(f"   Failed Tests: {sandbox.get('failed_tests')}")
            if sandbox.get("failure_reason"):
                print("   Failure Reason:")
                for line in str(sandbox.get("failure_reason")).splitlines()[:8]:
                    print(f"      {line}")
            elif sandbox.get("error"):
                print(f"   Failure Reason: {sandbox.get('error')}")

        pr_status = result.get("pr_status")
        pr_error = result.get("pr_error")
        pr_result = result.get("pr_result") or {}
        if pr_status:
            print(f"   PR Status: {pr_status}")
        if pr_result.get("pr_url"):
            print(f"   PR URL: {pr_result.get('pr_url')}")
        if pr_error:
            print(f"   PR Error: {pr_error}")

    if batch_result.get("halted"):
        print(f"\nQueue halted: {batch_result.get('halt_reason')}")

    print("\nBATCH SUMMARY")
    print(f"   Requested : {batch_result.get('total_requested', 0)}")
    print(f"   Processed : {batch_result.get('processed', 0)}")
    print(f"   Successful: {batch_result.get('successful', 0)}")
    print(f"   Halted    : {batch_result.get('halted', False)}")

    post_batch = batch_result.get("post_batch_validation") or {}
    if post_batch:
        print("\nPOST-BATCH DOCKER FULL-SUITE VALIDATION")
        print(f"   Status    : {post_batch.get('status')}")
        print(f"   Success   : {post_batch.get('success')}")
        if post_batch.get("error"):
            print(f"   Error     : {post_batch.get('error')}")
        sandbox_payload = post_batch.get("sandbox_result") or {}
        if sandbox_payload.get("failed_tests"):
            print(f"   Failed Tests: {sandbox_payload.get('failed_tests')}")
        if post_batch.get("llm_feedback"):
            print("   LLM Feedback (tail):")
            for line in str(post_batch.get("llm_feedback")).splitlines()[-10:]:
                print(f"      {line}")

    auto_repair = batch_result.get("post_batch_auto_repair") or {}
    if auto_repair:
        print("\nPOST-BATCH AUTO-REPAIR CYCLE")
        print(f"   Enabled   : {auto_repair.get('enabled')}")
        print(f"   Processed : {auto_repair.get('processed', 0)}")
        print(f"   Successful: {auto_repair.get('successful', 0)}")
        print(f"   Max Attempts/Ticket: {auto_repair.get('max_attempts_per_ticket', 1)}")
        for item in auto_repair.get("results", [])[:10]:
            print(
                "   "
                f"{item.get('ticket_key')} -> status={item.get('status')} "
                f"success={item.get('success')} attempts={item.get('attempt_count', 1)}"
            )
            if item.get("error"):
                print(f"      error={item.get('error')}")

    print(f"\n{REPORT_START_MARKER}")
    print(json.dumps(detailed_report, indent=2, default=str))
    print(REPORT_END_MARKER)

    print("\n" + "=" * 60)
    print("  FULL PIPELINE TEST COMPLETE")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    run_test()
