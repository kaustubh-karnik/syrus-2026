from app.mcp import JiraMCPClient
from app.config import get_settings


class TicketService:

    def __init__(self):
        pass

    def _get_client(self):
        """Create a fresh Jira client with current credentials from .env on every call"""
        settings = get_settings(reload=True)
        return JiraMCPClient(
            jira_url=settings.JIRA_URL,
            email=settings.JIRA_EMAIL,
            api_token=settings.JIRA_API_TOKEN,
            project_key=settings.JIRA_PROJECT_KEY,
            excluded_ticket_keys=settings.jira_excluded_ticket_keys,
        )

    def fetch_tickets(self, limit=None):
        client = self._get_client()
        return client.search_issues(max_results=limit)

    def fetch_ticket(self, key):
        client = self._get_client()
        return client.get_issue(key)
