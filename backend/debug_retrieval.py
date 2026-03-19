import json
import sys

sys.path.append(".")

from jira.exceptions import JIRAError

from app.agents.ticket_analyzer import ticket_analyzer_node
from app.agents.vector_search import vector_search_node
from app.config import settings
from app.mcp.jira_client import JiraMCPClient


def _print_json(title: str, payload: dict) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(payload, indent=2, default=str))


def _fetch_ticket(ticket_key: str) -> dict:
    jira = JiraMCPClient(
        jira_url=settings.JIRA_URL,
        email=settings.JIRA_EMAIL,
        api_token=settings.JIRA_API_TOKEN,
        project_key=settings.JIRA_PROJECT_KEY,
    )
    return jira.get_issue(ticket_key)


def _list_sample_tickets() -> list:
    jira = JiraMCPClient(
        jira_url=settings.JIRA_URL,
        email=settings.JIRA_EMAIL,
        api_token=settings.JIRA_API_TOKEN,
        project_key=settings.JIRA_PROJECT_KEY,
    )
    return jira.search_issues(max_results=10)


def run_debug(ticket_key: str) -> None:
    ticket = _fetch_ticket(ticket_key)
    _print_json("TICKET", ticket)

    analysis_state = ticket_analyzer_node({"ticket": ticket})
    _print_json("ANALYSIS", analysis_state)

    retrieval_state = {
        "ticket": ticket,
        "repo_id": settings.TARGET_REPO_ID,
        "commit_sha": settings.TARGET_REPO_COMMIT_SHA,
        "bug_type": analysis_state.get("bug_type"),
        "keywords": analysis_state.get("keywords"),
        "likely_files": analysis_state.get("likely_files"),
        "service": analysis_state.get("service"),
        "confidence": analysis_state.get("confidence"),
        "root_cause_hint": analysis_state.get("root_cause_hint"),
    }

    retrieval_result = vector_search_node(retrieval_state)
    retrieval_context = retrieval_result.get("retrieval_context", {})
    summary = {
        "status": retrieval_result.get("status"),
        "error": retrieval_result.get("error"),
        "query": retrieval_context.get("query"),
        "repo_state": retrieval_context.get("repo_state"),
        "repo_profile": retrieval_context.get("repo_profile"),
        "symbol_graph_summary": retrieval_context.get("symbol_graph_summary"),
        "validation_context": retrieval_context.get("validation_context"),
        "validation_plan": retrieval_context.get("validation_plan"),
        "remote_signals": retrieval_context.get("remote_signals"),
        "ranked_files": retrieval_context.get("ranked_files", [])[:10],
        "context_text_preview": (retrieval_context.get("context_text") or "")[:2000],
    }
    _print_json("RETRIEVAL", summary)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python backend/debug_retrieval.py <JIRA_TICKET_KEY>")
        sys.exit(1)

    try:
        run_debug(sys.argv[1])
    except JIRAError as exc:
        print("\nJira lookup failed.")
        print(f"Requested key: {sys.argv[1]}")
        print(f"Error: {exc.text or str(exc)}")
        sample_tickets = _list_sample_tickets()
        if sample_tickets:
            print("\nAvailable tickets in configured Jira project:")
            for ticket in sample_tickets:
                print(f"- {ticket['jira_key']}: {ticket['summary']}")
        else:
            print("\nNo accessible tickets were returned from the configured Jira project.")
        sys.exit(1)
