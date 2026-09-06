# DevSync — AI-Powered Developer Investigation Assistant

DevSync helps developers investigate bugs without manually switching between **Jira, Slack, and PostgreSQL** to gather and correlate context.

When a developer encounters an issue, the information needed to understand it is often spread across multiple systems. Jira may contain the issue description and comments, Slack may contain discussions and debugging attempts, while the database may contain the actual runtime evidence.

DevSync brings these sources together and uses Gemini to investigate the issue and generate a single, evidence-based report.

## The Problem

A typical bug investigation can involve:

- Reading the Jira ticket and its comments
- Searching Slack for related conversations
- Checking database records
- Connecting information from different sources
- Determining what is actually known versus what is only a hypothesis

This creates unnecessary context switching and makes investigations time-consuming.

**DevSync's goal is to bring the relevant context to the developer instead of making the developer manually search for it.**

## How It Works

A developer starts an investigation with a Jira issue:

"Investigate SCRUM-1"

DevSync then allows Gemini to determine what information is required and which tools should be used.

Developer
    |
    v
DevSync
    |
    v
Gemini + MCP Client
    |
    +----------+----------+
    |          |          |
    v          v          v
  Jira       Slack    PostgreSQL
    |          |          |
    +----------+----------+
               |
               v
        Gathered Evidence
               |
               v
        Correlated Context
               |
               v
       Investigation Report

There is no hardcoded sequence such as:

Jira → Slack → PostgreSQL

Gemini can choose the tools it needs and invoke them in the order required for the investigation.

MCP Architecture

DevSync uses Model Context Protocol (MCP) as the interface between the investigation agent and the external systems.

The application consists of one MCP client and three independent MCP servers:

                    Gemini
                       |
                       v
                  MCP Client
                       |
          +------------+------------+
          |            |            |
          v            v            v
      Jira MCP     Slack MCP    PostgreSQL MCP
       Server        Server        Server
          |            |            |
          v            v            v
        Jira         Slack      PostgreSQL 

The client does not contain Jira-, Slack-, or PostgreSQL-specific implementation logic. It interacts with the tools exposed by the MCP servers.

For this first version, I implemented the MCP client and all three MCP servers myself to understand the complete MCP flow — from tool discovery and invocation to receiving results and feeding them back into the LLM.

The servers communicate with the client through stdio, while each server can independently use whatever mechanism it needs internally, such as REST APIs or a database connection.

## Investigation Example

Suppose a Jira issue reports:

Payment succeeded, but the order is still stuck in PROCESSING.

DevSync can gather:

Jira

Issue details
Comments
Related issues

Slack

Relevant discussions
Debugging conversations
Related messages and threads

PostgreSQL

Payment status
Order status
Other relevant records

Gemini then correlates the retrieved information and produces a report such as:

Evidence:
• Payment is marked SUCCESS.
• The corresponding order remains PROCESSING.
• Slack contains a discussion about payment callback failures.

Hypothesis:
The payment callback may not have been processed correctly.

The hypothesis is based on the retrieved evidence and is
not presented as a confirmed root cause.

The purpose is to give the developer the relevant context and evidence in one place, rather than requiring them to manually reconstruct it.

## Database Safety

Because the investigation agent can request database information, PostgreSQL access is strictly read-only.

The MCP server uses multiple layers of protection:

A dedicated PostgreSQL role with only SELECT permissions.
A read-only database session.
Application-level SQL validation before a query reaches the database.

This means database permissions provide the actual security boundary rather than relying only on instructions given to the LLM.

Evidence vs. Hypothesis

DevSync explicitly separates:

Evidence — information retrieved directly from Jira, Slack, or PostgreSQL.

Hypothesis — a possible explanation inferred from that evidence.

The system prompt instructs Gemini not to present an inferred explanation as a confirmed root cause.

This distinction is currently enforced at the prompting level, rather than through a formal programmatic verification layer.

## Current Scope

The current version focuses specifically on cross-system developer context gathering and investigation.

It intentionally keeps the scope limited to:

Jira
  +
Slack
  +
PostgreSQL
  ↓
Context Gathering
  ↓
Evidence Correlation
  ↓
Investigation

The UI is intentionally minimal, with Streamlit used primarily to provide an interface for running investigations while keeping the focus on the underlying MCP and investigation workflow.

## Core Idea

DevSync reduces the context-switching involved in debugging by bringing relevant engineering information from multiple systems into a single AI-assisted investigation.

MCP is the architectural layer that connects the agent to these different tools; the actual goal is reducing the manual effort developers spend gathering and correlating context.
