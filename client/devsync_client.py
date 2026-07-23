"""
DevSync Client
--------------
Connects to the three MCP servers (Jira, Slack, Postgres) over stdio,
gives Gemini the combined tool list, and lets Gemini decide which
tools to call and in what order to investigate a ticket.

Usage:
    python client/devsync_client.py "Investigate PAY-102"

This file intentionally has one job: wire MCP <-> Gemini together and
run the tool-calling loop. It does not contain any Jira/Slack/Postgres
specific logic - that all lives inside the MCP servers themselves.
That separation is the whole point of the architecture.
"""

import asyncio
import os
import sys
from contextlib import AsyncExitStack

from google import genai
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

SYSTEM_PROMPT = """You are DevSync, a developer context assistant.

A developer will give you a Jira ticket key or a short description of
an issue. Your job is to gather context from three independent
systems - Jira, Slack, and a Postgres database - and produce a single
correlated investigation report. You do not fix bugs or modify data.

Process:
1. Look up the Jira issue and its comments to understand what was reported.
2. Search Slack for related discussion using concepts from the Jira issue
   (e.g. the affected feature area, not the literal ticket text). If a
   relevant message is found, pull the full thread with get_thread.
3. Inspect the Postgres schema/tables relevant to the issue, then run a
   read-only SELECT to look for supporting or contradicting evidence in
   the actual data.
4. Produce a final report with these exact sections:
   ## Issue
   ## Jira Context
   ## Relevant Team Context (Slack)
   ## Database Observations
   ## Likely Investigation Area
   ## Suggested Developer Investigation

Clearly separate observed evidence (things you directly retrieved) from
hypotheses (your interpretation of why they might be happening). Never
state a suspected root cause as if it were confirmed. If a source has
nothing relevant, say so plainly instead of guessing.
"""


class DevSyncClient:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is missing. Add it to your .env file.")
        self.gemini = genai.Client(api_key=api_key)
        self.exit_stack = AsyncExitStack()
        self.sessions: dict[str, ClientSession] = {}
        self.tool_to_server: dict[str, str] = {}
        self.available_tools: list[dict] = []

    async def connect_server(self, name: str, script_path: str):
        params = StdioServerParameters(command=sys.executable, args=[script_path])
        read, write = await self.exit_stack.enter_async_context(stdio_client(params))
        session = await self.exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self.sessions[name] = session

        response = await session.list_tools()
        for tool in response.tools:
            self.tool_to_server[tool.name] = name
            self.available_tools.append(
                {
                    "type": "function",
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema,
                }
            )
        print(f"[connected] {name}: {[t.name for t in response.tools]}")

    async def call_tool(self, tool_name: str, tool_args: dict) -> str:
        server_name = self.tool_to_server[tool_name]
        session = self.sessions[server_name]
        result = await session.call_tool(tool_name, tool_args)
        return "\n".join(
            block.text for block in result.content if hasattr(block, "text")
        )

    async def investigate(self, user_query: str) -> str:
        interaction = self.gemini.interactions.create(
            model=MODEL,
            system_instruction=SYSTEM_PROMPT,
            input=user_query,
            tools=self.available_tools,
        )

        while True:
            tool_calls = [
                step for step in interaction.steps
                if step.type == "function_call"
            ]

            if not tool_calls:
                return interaction.output_text or "(Gemini returned no text.)"

            function_results = []
            for call in tool_calls:
                args = dict(call.arguments or {})
                print(f"  -> calling {call.name}({args})")

                try:
                    result_text = await self.call_tool(call.name, args)
                except Exception as exc:
                    result_text = f"Tool execution failed: {exc}"

                function_results.append(
                    {
                        "type": "function_result",
                        "name": call.name,
                        "call_id": call.id,
                        "result": [{"type": "text", "text": result_text}],
                    }
                )

            interaction = self.gemini.interactions.create(
                model=MODEL,
                input=function_results,
                tools=self.available_tools,
                previous_interaction_id=interaction.id,
            )

    async def cleanup(self):
        await self.exit_stack.aclose()


async def main():
    if len(sys.argv) < 2:
        print('Usage: python devsync_client.py "Investigate PAY-102"')
        return

    query = " ".join(sys.argv[1:])
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    client = DevSyncClient()
    try:
        await client.connect_server("jira", os.path.join(base, "mcp_servers", "jira_server.py"))
        await client.connect_server("slack", os.path.join(base, "mcp_servers", "slack_server.py"))
        await client.connect_server("postgres", os.path.join(base, "mcp_servers", "postgres_server.py"))

        print(f"\n--- Investigating with {MODEL} ---\n")
        report = await client.investigate(query)
        print("\n--- Report ---\n")
        print(report)
    finally:
        await client.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
