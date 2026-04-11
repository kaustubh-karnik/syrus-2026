from pathlib import Path

from app.agents.state import AgentState
from app.config import settings
from app.mcp.github_client import GitHubMCPClient


def create_pr_node(state: AgentState) -> AgentState:
    """
    LangGraph-compatible node: create a GitHub Pull Request after successful
    patch + sandbox validation.
    """

    print("\n[PR] Create PR: starting...")

    patch_result = state.get("patch_result") or {}
    sandbox_result = state.get("sandbox_result") or {}
    promotion_result = state.get("promotion_result") or {}

    if not patch_result.get("success"):
        print("   [SKIP] patch not successful")
        return {
            "pr_result": None,
            "status": "pr_skipped",
            "error": None,
        }

    if not settings.GITHUB_TOKEN:
        print("   [SKIP] GITHUB_TOKEN not configured")
        return {
            "pr_result": None,
            "status": "pr_skipped",
            "error": "GITHUB_TOKEN not set",
        }

    modified_files = [
        str(item or "").replace("\\", "/").strip()
        for item in (
            promotion_result.get("promoted_files")
            or patch_result.get("modified_files")
            or []
        )
        if str(item or "").strip()
    ]
    primary_file = patch_result.get("file") or (modified_files[0] if modified_files else "")

    ticket = state.get("ticket") or {}
    ticket_key = str(ticket.get("jira_key") or "UNKNOWN").strip()
    ticket_summary = str(ticket.get("summary") or "Automated bug fix").strip()
    fix = state.get("fix") or {}
    fix_reason = str(fix.get("reason") or "Automated bug fix from sandbox-validated pipeline").strip()

    print(f"   Ticket     : {ticket_key}")
    print(f"   Files      : {modified_files or [primary_file]}")
    test_passed = bool(sandbox_result.get("success"))
    print(f"   Tests      : {'PASSED' if test_passed else 'FAILED'}")

    if not primary_file:
        return {
            "pr_result": None,
            "status": "pr_failed",
            "error": "No patched file available to create a PR",
        }

    base_repo_path = str(state.get("base_repo_path") or "").strip()
    if not base_repo_path:
        return {
            "pr_result": None,
            "status": "pr_failed",
            "error": "Target repository path is missing in state",
        }

    repo_root = Path(base_repo_path).resolve()
    primary_path = repo_root / primary_file
    if not primary_path.exists():
        return {
            "pr_result": None,
            "status": "pr_failed",
            "error": f"Patched file not found in target repository: {primary_file}",
        }

    try:
        fixed_content = primary_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {
            "pr_result": None,
            "status": "pr_failed",
            "error": f"Could not read patched file: {exc}",
        }

    try:
        client = GitHubMCPClient()
        pr_result = client.create_fix_pr(
            ticket_key=ticket_key,
            file_path=primary_file,
            fixed_content=fixed_content,
            ticket_summary=ticket_summary,
            fix_reason=fix_reason,
            test_passed=test_passed,
            file_paths=modified_files,
            repo_root=str(repo_root),
        )

        print("\n[OK] Pull Request created:")
        print(f"   PR #{pr_result.get('pr_number')}: {pr_result.get('pr_url')}")
        print(f"   Branch: {pr_result.get('branch')}")
        if pr_result.get("commit_sha"):
            print(f"   Commit: {str(pr_result.get('commit_sha'))[:7]}")

        return {
            "pr_result": pr_result,
            "status": "pr_created",
            "error": None,
        }
    except Exception as exc:
        print(f"[ERROR] Failed to create PR: {exc}")
        return {
            "pr_result": None,
            "status": "pr_failed",
            "error": f"PR creation failed: {exc}",
        }
