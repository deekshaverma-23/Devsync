# DevSync — MCP-Based Developer Context Assistant

An MCP-powered assistant that investigates a Jira ticket by pulling
context from Jira, Slack, and Postgres, and correlating it into one
report — instead of you tab-switching between three tools.

## Architecture

```
Developer
   |
   v
devsync_client.py  (uses the Gemini API)
   |
   v
MCP Client (one ClientSession per server)
   |
   +--> jira_server.py      (REAL Jira Cloud, REST API v3)
   +--> slack_server.py     (REAL Slack workspace, Web API)
   +--> postgres_server.py  (REAL Postgres, read-only)
```

All three servers are spawned as local subprocesses and talk to the
client over **stdio** — the same local pipe mechanism the whole time,
whether the tool's internals hit a database, an HTTP API, or (as in
earlier versions of this project) a local JSON file. That's worth
being explicit about: stdio is the *transport* between your client and
your MCP server, completely separate from whatever the server does
*inside* a tool function to actually fetch data. Nothing here is a
remotely-hosted MCP server — that's a different, optional MCP feature
this project deliberately doesn't need.

Three independent MCP servers, one client, one LLM in the loop. Gemini
decides which tools to call and in what order — there's no hardcoded
pipeline telling it "always call Jira then Slack then Postgres."

**Why MCP instead of calling the Jira/Slack/Postgres APIs directly?**
Direct integration would work fine functionally. The point of MCP here
is standardization and modularity: `devsync_client.py` uses Gemini only for reasoning/tool selection and never contains
any Jira-specific or Slack-specific code. It only knows "call this
tool with these arguments." Each server's internals can change
completely without touching the client or the LLM-facing tool contract
at all — this project actually went through that exact change, from
simulated JSON data to real APIs, with zero changes to the client.

## Setup

### 1. Postgres

Assumes you already have Postgres installed and running locally.

```bash
createdb devsync
psql -U postgres -d devsync -f db/init.sql
```

`db/init.sql`:
- creates `users`, `orders`, `payments`
- seeds data that already contains the bug evidence (e.g. payments
  with `status = SUCCESS` whose orders are stuck at `PROCESSING`)
- creates a `devsync_readonly` Postgres role with **only SELECT
  grants** — no INSERT/UPDATE/DELETE/DDL. The MCP server connects as
  this role, so the read-only restriction is enforced by Postgres
  itself, not just by a system prompt.

Sanity-check it:
```bash
psql -U devsync_readonly -d devsync -c "SELECT * FROM orders;"
```

### 2. Jira

- Create an API token at
  `https://id.atlassian.com/manage-profile/security/api-tokens`
- Create a project and a few issues (title + description + comments)
  to investigate
- Note your site URL, account email, and the issue keys you created

### 3. Slack

- Create a Slack app at `https://api.slack.com/apps` → **From scratch**
- Under **OAuth & Permissions → Bot Token Scopes**, add:
  `channels:history`, `channels:read`
  (`search:read` is a *user*-token scope and won't work on a bot
  token — this project doesn't use it; see "Design notes" below)
- Install the app to your workspace, copy the **Bot User OAuth Token**
  (`xoxb-...`)
- Create the channels you want the assistant to search, and invite the
  bot into each one: `/invite @your-bot-name`

### 4. Install Python dependencies

```bash
python -m venv venv
source venv/Scripts/activate   # Windows Git Bash; use venv/bin/activate on Mac/Linux
pip install -r requirements.txt
```

### 5. Configure environment

```bash
cp .env.example .env
```

Fill in `.env`:
- `GEMINI_API_KEY` — create one in Google AI Studio\n- `GEMINI_MODEL` — optional; defaults to `gemini-3.6-flash`
- `PG_*` — match whatever you used in step 1 (default port is 5432,
  double check yours)
- `JIRA_SITE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` from step 2
- `SLACK_BOT_TOKEN` from step 3, and `SLACK_CHANNELS` — a
  comma-separated list of the channel names the bot was invited into

### 6. Run

```bash
python client/devsync_client.py "Investigate SCRUM-1"
```

Use whatever issue key you actually created in step 2 — Jira
auto-numbers per project, so it likely isn't literally `PAY-102`
unless you renamed the project key.

You'll see which tools Gemini calls, in what order, followed by the
final correlated report.

## Project layout

```
devsync/
├── db/init.sql                 # schema + seed data + read-only role (run manually with psql)
├── mcp_servers/
│   ├── postgres_server.py      # get_schema, describe_table, run_read_query
│   ├── jira_server.py          # get_issue, get_issue_comments, search_issues
│   └── slack_server.py         # search_messages, get_thread
├── client/
│   └── devsync_client.py       # connects to all 3 servers, runs the tool-use loop
├── requirements.txt
└── .env.example
```

## Database safety, explained

`run_read_query` in `postgres_server.py` has three independent layers,
so a single mistake anywhere doesn't turn into a write:

1. **DB role**: connects as `devsync_readonly`, which only has SELECT
   grants at the Postgres permission level.
2. **Session flag**: `conn.set_session(readonly=True)` — Postgres
   rejects writes in the session itself.
3. **Query validation in code**: rejects anything that isn't a single
   SELECT statement, and rejects it *before* it reaches the database.

Any one of these being disabled would still leave the other two.

## Evidence vs. hypothesis

The system prompt in `devsync_client.py` explicitly instructs Gemini
to separate what it *retrieved* (evidence) from what it *infers*
(hypothesis), and to never present a hypothesis as a confirmed root
cause. This is a prompting decision, not a code-level constraint —
worth being upfront about that distinction if you're asked.

## Design notes worth knowing for questions

- **Why not `search.messages` for Slack search?** That endpoint
  requires a user token and, on many workspace tiers, a paid plan.
  `search_messages` instead pulls `conversations.history` for the
  configured channels and filters by keyword in code — functionally
  similar for a small demo workspace, and it only needs bot-token
  scopes.
- **Why does the bot need to be invited into channels?** Slack bots
  can only read channels they're a member of, regardless of scopes
  granted — this is a Slack platform restriction, not something this
  project chose.
- **Why HTTP for Jira/Slack calls but stdio for MCP transport?** These
  are two different layers. The MCP client-to-server connection
  (stdio) never changed; only what a tool function does internally
  (JSON file read → HTTP API call) changed when the real accounts
  were wired in.

## Explicitly out of scope (by design)

Multi-agent orchestration, LangGraph, RAG/vector search, autonomous
code changes, GitHub/PR integration, remote/hosted MCP transport, and
any DB write path. The project is meant to demonstrate MCP itself —
tool discovery, tool invocation, and cross-system context correlation
through a standard interface — not to look architecturally impressive.
