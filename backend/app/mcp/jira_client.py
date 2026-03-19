import warnings

warnings.filterwarnings("ignore", category=RuntimeWarning)

from typing import Dict, List, Optional

import requests
from jira import JIRA


class JiraMCPClient:

    def __init__(
        self,
        jira_url: str,
        email: str,
        api_token: str,
        project_key: str = "ST",
        excluded_ticket_keys: Optional[List[str]] = None,
    ):
        self.jira_url = jira_url.rstrip("/")
        self.email = email
        self.api_token = api_token
        self.project_key = project_key
        self.excluded_ticket_keys = [
            str(item).strip().upper()
            for item in (excluded_ticket_keys or [])
            if str(item).strip()
        ]

        self.jira = JIRA(
            server=jira_url,
            basic_auth=(email, api_token),
            options={"rest_api_version": "3"}
        )

        print("[OK] Connected to Jira")

    def get_issue(self, issue_key: str) -> Dict:

        issue = self.jira.issue(issue_key)

        return {
            "jira_key": issue.key,
            "summary": issue.fields.summary,
            "description": issue.fields.description or "",
            "priority": issue.fields.priority.name if issue.fields.priority else "Medium",
            "status": issue.fields.status.name,
        }

    def search_issues(self, max_results: Optional[int] = 20) -> List[Dict]:

        project_key = str(self.project_key or "").strip()
        exclusion_clause = ""
        if self.excluded_ticket_keys:
            excluded = ", ".join(f'"{key}"' for key in self.excluded_ticket_keys)
            exclusion_clause = f" AND key NOT IN ({excluded})"

        jql = f'project = "{project_key}"{exclusion_clause} ORDER BY created DESC'

        url = f"{self.jira_url}/rest/api/3/search/jql"

        requested_total = None
        if max_results is not None and int(max_results) > 0:
            requested_total = int(max_results)

        page_size = 100 if requested_total is None else min(100, requested_total)
        next_page_token: Optional[str] = None
        results: List[Dict] = []

        try:
            while True:
                payload = {
                    "jql": jql,
                    "maxResults": page_size,
                    "fields": ["summary", "description", "priority", "status"],
                }
                if next_page_token:
                    payload["nextPageToken"] = next_page_token

                response = requests.post(
                    url,
                    auth=(self.email, self.api_token),
                    json=payload,
                    headers={"Content-Type": "application/json"}
                )

                response.raise_for_status()
                data = response.json()
                issues = data.get("issues", []) or []

                for issue in issues:
                    fields = issue.get("fields", {})
                    results.append({
                        "jira_key": issue.get("key"),
                        "summary": fields.get("summary", "No summary"),
                        "description": fields.get("description", ""),
                        "priority": fields.get("priority", {}).get("name", "Medium"),
                        "status": fields.get("status", {}).get("name", "Unknown")
                    })

                fetched_count = len(issues)
                if fetched_count == 0:
                    break

                if requested_total is not None and len(results) >= requested_total:
                    return results[:requested_total]

                next_page_token = data.get("nextPageToken")
                is_last = bool(data.get("isLast"))
                if is_last or not next_page_token:
                    break

            return results

        except requests.HTTPError as exc:
            response = exc.response
            details = ""
            if response is not None:
                try:
                    error_json = response.json()
                    details = (
                        error_json.get("errorMessages")
                        or error_json.get("errors")
                        or error_json
                    )
                except Exception:
                    details = response.text

                print(
                    "[WARN] Jira search failed: "
                    f"status={response.status_code} url={response.url} "
                    f"jql={jql} details={details}"
                )
            else:
                print(f"[WARN] Jira search failed (no response): {exc}")
            return []
        except Exception as e:
            print(f"[WARN] Search error: {e}")
            return []


if __name__ == "__main__":

    from app.config import settings

    print("\n=== Testing Jira MCP Client ===\n")

    client = JiraMCPClient(
        jira_url=settings.JIRA_URL,
        email=settings.JIRA_EMAIL,
        api_token=settings.JIRA_API_TOKEN,
        project_key=settings.JIRA_PROJECT_KEY,
        excluded_ticket_keys=settings.jira_excluded_ticket_keys,
    )

    print("\nFetching tickets...\n")

    tickets = client.search_issues(max_results=None)

    if tickets:
        print(f"Found {len(tickets)} tickets:\n")

        for t in tickets:
            print(f"{t['jira_key']} -> {t['summary']}")
    else:
        print("[WARN] No tickets found")

    print("\n=== Test Finished ===\n")