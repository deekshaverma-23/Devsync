import asyncio
import os

import streamlit as st

from client.devsync_client import DevSyncClient


st.set_page_config(
    page_title="DevSync",
    page_icon="🔎",
    layout="wide",
)

st.title("🔎 DevSync")
st.subheader("AI-Powered Developer Context Assistant")

st.write(
    "Investigate engineering issues across Jira, Slack and PostgreSQL "
    "using Gemini + MCP."
)

issue_key = st.text_input(
    "Jira Issue",
    value="SCRUM-1",
    placeholder="e.g. SCRUM-1",
)


async def run_investigation(issue):
    client = DevSyncClient()

    base = os.path.dirname(os.path.abspath(__file__))

    try:
        await client.connect_server(
            "jira",
            os.path.join(base, "mcp_servers", "jira_server.py"),
        )

        await client.connect_server(
            "slack",
            os.path.join(base, "mcp_servers", "slack_server.py"),
        )

        await client.connect_server(
            "postgres",
            os.path.join(base, "mcp_servers", "postgres_server.py"),
        )

        return await client.investigate(
            f"Investigate {issue}"
        )

    finally:
        await client.cleanup()


if st.button("Investigate", type="primary"):

    if not issue_key.strip():
        st.warning("Enter a Jira issue key.")

    else:

        with st.spinner(
            "Gemini is investigating Jira, Slack and PostgreSQL..."
        ):

            try:
                report = asyncio.run(
                    run_investigation(issue_key.strip())
                )

                st.success("Investigation complete")

                st.markdown("---")

                st.markdown(report)

            except Exception as e:
                error = str(e)

                if "429" in error or "quota" in error.lower():
                    st.warning(
                        "Gemini API quota is temporarily exhausted. "
                        "Please try again after the quota resets."
                    )
                else:
                    st.error("Investigation failed")
                    st.exception(e)