"""
DevSync - Jira MCP Server
--------------------------
Exposes get_issue, get_issue_comments, search_issues.

This talks to a REAL Jira Cloud site over its REST API. The MCP
transport (stdio, spawned by devsync_client.py) is unchanged from the
simulated version - only what happens INSIDE each tool function
changed, from a JSON lookup to an HTTP call.

Auth: Jira Cloud uses HTTP Basic Auth with your Atlassian account
email + an API token (not your password). 
"""

import os
import requests
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("jira-server")

JIRA_SITE_URL = os.getenv("JIRA_SITE_URL", "").rstrip("/")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")

_AUTH = (JIRA_EMAIL, JIRA_API_TOKEN)
_HEADERS = {"Accept": "application/json"}


def _adf_to_text(node) -> str:
    """
    Jira Cloud returns descriptions/comments as Atlassian Document
    Format (a nested JSON tree), not plain text. This walks the tree
    and pulls out just the text content.
    """
    if node is None:
        return ""
    if isinstance(node, str):
        return node

    text_parts = []
    if isinstance(node, dict):
        if node.get("type") == "text":
            text_parts.append(node.get("text", ""))
        for child in node.get("content", []) or []:
            text_parts.append(_adf_to_text(child))
        if node.get("type") in ("paragraph", "heading"):
            text_parts.append("\n")
    elif isinstance(node, list):
        for item in node:
            text_parts.append(_adf_to_text(item))

    return "".join(text_parts)


def _get(path: str, params: dict | None = None) -> requests.Response:
    return requests.get(
        f"{JIRA_SITE_URL}{path}",
        auth=_AUTH,
        headers=_HEADERS,
        params=params,
        timeout=15,
    )


@mcp.tool()
def get_issue(issue_key: str) -> str:
    """Get title, description, priority, status, and metadata for a Jira issue key (e.g. SCRUM-1)."""
    resp = _get(f"/rest/api/3/issue/{issue_key.upper()}")
    if resp.status_code == 404:
        return f"No issue found with key {issue_key}"
    if not resp.ok:
        return f"Jira API error ({resp.status_code}): {resp.text[:300]}"

    data = resp.json()
    fields = data["fields"]

    priority = (fields.get("priority") or {}).get("name", "Unset")
    status = (fields.get("status") or {}).get("name", "Unknown")
    assignee = (fields.get("assignee") or {}).get("displayName", "Unassigned")
    components = [c["name"] for c in fields.get("components", [])]
    labels = fields.get("labels", [])
    description = _adf_to_text(fields.get("description")).strip() or "(no description)"

    return (
        f"[{issue_key.upper()}] {fields.get('summary', '')}\n"
        f"Priority: {priority} | Status: {status} | Assignee: {assignee}\n"
        f"Components: {', '.join(components) or 'none'} | Labels: {', '.join(labels) or 'none'}\n"
        f"Created: {fields.get('created', '')}\n\n"
        f"Description:\n{description}"
    )


@mcp.tool()
def get_issue_comments(issue_key: str) -> str:
    """Get all comments/discussion attached to a Jira issue key."""
    resp = _get(f"/rest/api/3/issue/{issue_key.upper()}/comment")
    if resp.status_code == 404:
        return f"No issue found with key {issue_key}"
    if not resp.ok:
        return f"Jira API error ({resp.status_code}): {resp.text[:300]}"

    comments = resp.json().get("comments", [])
    if not comments:
        return "No comments on this issue."

    lines = [f"Comments on {issue_key.upper()}:"]
    for c in comments:
        author = c.get("author", {}).get("displayName", "unknown")
        created = c.get("created", "")
        body = _adf_to_text(c.get("body")).strip()
        lines.append(f"- [{created}] {author}: {body}")
    return "\n".join(lines)


@mcp.tool()
def search_issues(query: str) -> str:
    """Search issues by keyword across summary and description. Use this to find potentially related tickets."""
    jql = f'text ~ "{query}"'
    resp = _get("/rest/api/3/search", params={"jql": jql, "maxResults": 10})
    if not resp.ok:
        return f"Jira API error ({resp.status_code}): {resp.text[:300]}"

    issues = resp.json().get("issues", [])
    if not issues:
        return f"No issues matched '{query}'."

    lines = ["Matching issues:"]
    for issue in issues:
        key = issue["key"]
        summary = issue["fields"].get("summary", "")
        status = (issue["fields"].get("status") or {}).get("name", "Unknown")
        lines.append(f"[{key}] {summary} ({status})")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
