from app.mcp import JiraMCPClient
from app.config import settings


class TicketService:

    def __init__(self):
        self.client = JiraMCPClient(
            jira_url=settings.JIRA_URL,
            email=settings.JIRA_EMAIL,
            api_token=settings.JIRA_API_TOKEN,
            project_key=settings.JIRA_PROJECT_KEY,
            excluded_ticket_keys=settings.jira_excluded_ticket_keys,
        )

    def fetch_tickets(self, limit=None):
        return self.client.search_issues(max_results=limit)

    def fetch_ticket(self, key):
        return self.client.get_issue(key)