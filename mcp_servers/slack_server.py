import os
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

load_dotenv()

mcp = FastMCP("slack-server")

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_CHANNELS = [
    c.strip() for c in os.getenv("SLACK_CHANNELS", "").split(",") if c.strip()
]

_client = WebClient(token=SLACK_BOT_TOKEN)

_channel_id_cache: dict[str, str] = {}
_user_name_cache: dict[str, str] = {}


def _get_channel_id(channel_name: str) -> str | None:
    if channel_name in _channel_id_cache:
        return _channel_id_cache[channel_name]

    cursor = None
    while True:
        resp = _client.conversations_list(
            types="public_channel", cursor=cursor, limit=200
        )
        for ch in resp["channels"]:
            _channel_id_cache[ch["name"]] = ch["id"]
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break

    return _channel_id_cache.get(channel_name)


def _user_display_name(user_id: str) -> str:
    if user_id in _user_name_cache:
        return _user_name_cache[user_id]
    try:
        resp = _client.users_info(user=user_id)
        name = resp["user"].get("real_name") or resp["user"].get("name") or user_id
    except SlackApiError:
        name = user_id
    _user_name_cache[user_id] = name
    return name


@mcp.tool()
def search_messages(query: str) -> str:
    """Search Slack messages by keyword (e.g. 'payment callback', 'password reset') across the configured channels. Returns matching messages with a thread_id so get_thread can retrieve full context."""
    if not SLACK_CHANNELS:
        return "No channels configured. Set SLACK_CHANNELS in .env."

    query_lower = query.lower()
    matches = []

    for channel_name in SLACK_CHANNELS:
        channel_id = _get_channel_id(channel_name)
        if not channel_id:
            continue
        try:
            resp = _client.conversations_history(channel=channel_id, limit=200)
        except SlackApiError as e:
            return f"Slack API error reading #{channel_name}: {e.response['error']}"

        for msg in resp.get("messages", []):
            text = msg.get("text", "")
            if query_lower in text.lower():
                matches.append(
                    {
                        "channel": channel_name,
                        "author": _user_display_name(msg.get("user", "unknown")),
                        "ts": msg["ts"],
                        "text": text,
                        "thread_id": f"{channel_name}:{msg['ts']}",
                    }
                )

    if not matches:
        return f"No Slack messages matched '{query}'."

    lines = [f"Found {len(matches)} matching message(s):"]
    for m in matches:
        lines.append(
            f"- [#{m['channel']}] {m['author']} ({m['ts']}) thread_id={m['thread_id']}: {m['text']}"
        )
    return "\n".join(lines)


@mcp.tool()
def get_thread(thread_id: str) -> str:
    """Get the full discussion thread for a given thread_id (format 'channel_name:ts'), in chronological order."""
    try:
        channel_name, ts = thread_id.split(":", 1)
    except ValueError:
        return "Invalid thread_id. Expected format 'channel_name:ts'."

    channel_id = _get_channel_id(channel_name)
    if not channel_id:
        return f"Unknown channel: {channel_name}"

    try:
        resp = _client.conversations_replies(channel=channel_id, ts=ts)
    except SlackApiError as e:
        return f"Slack API error: {e.response['error']}"

    messages = resp.get("messages", [])
    if not messages:
        return f"No thread found for {thread_id}"

    lines = [f"Thread {thread_id} (#{channel_name}):"]
    for m in messages:
        author = _user_display_name(m.get("user", "unknown"))
        lines.append(f"- {author} ({m['ts']}): {m.get('text', '')}")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
