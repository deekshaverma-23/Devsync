"""
DevSync - Postgres MCP Server

Exposes a small, safe set of read-only capabilities over a real
Postgres database: get_schema, describe_table, run_read_query.

Safety model (defense in depth):
1. The server connects using the `devsync_readonly` DB role, which
   only has SELECT grants (see db/init.sql). Even if the code below
   had a bug, Postgres itself would reject a write.
2. `run_read_query` additionally rejects any statement that isn't a
   single SELECT, before it ever reaches the database.
3. Every query runs inside a READ ONLY transaction as a third layer.

"""

import os
import re
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("postgres-server")

DB_CONFIG = {
    "host": os.getenv("PG_HOST", "localhost"),
    "port": os.getenv("PG_PORT", "5432"),
    "dbname": os.getenv("PG_DATABASE", "devsync"),
    "user": os.getenv("PG_USER", "devsync_readonly"),
    "password": os.getenv("PG_PASSWORD", "devsync_readonly_pw"),
}

# Only a single SELECT statement is allowed hoga, nothing else.
_SELECT_ONLY = re.compile(r"^\s*SELECT\b", re.IGNORECASE)
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|GRANT|REVOKE|CREATE)\b",
    re.IGNORECASE,
)


def _get_connection():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.set_session(readonly=True, autocommit=True)
    return conn


@mcp.tool()
def get_schema() -> str:
    """Return the list of tables available in the public schema."""
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name;
                """
            )
            tables = [row[0] for row in cur.fetchall()]
    return "Tables:\n" + "\n".join(f"- {t}" for t in tables)


@mcp.tool()
def describe_table(table_name: str) -> str:
    """Return column names, types, and nullability for a given table."""
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position;
                """,
                (table_name,),
            )
            rows = cur.fetchall()

    if not rows:
        return f"No such table: {table_name}"

    lines = [f"Schema for '{table_name}':"]
    for col, dtype, nullable in rows:
        lines.append(f"- {col}: {dtype} (nullable={nullable})")
    return "\n".join(lines)


@mcp.tool()
def run_read_query(sql: str) -> str:
    """
    Run a read-only SELECT query against the database and return the
    results as text. Only a single SELECT statement is permitted -
    anything else (INSERT/UPDATE/DELETE/DDL, or multiple statements)
    is rejected before it reaches the database.
    """
    stripped = sql.strip().rstrip(";")

    if ";" in stripped:
        return "Rejected: only a single statement is allowed."
    if not _SELECT_ONLY.match(stripped):
        return "Rejected: only SELECT statements are allowed."
    if _FORBIDDEN.search(stripped):
        return "Rejected: query contains a disallowed keyword."

    try:
        with _get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(stripped)
                rows = cur.fetchmany(200)  # hard cap, this is a context tool not a report generator
    except Exception as exc:
        return f"Query failed: {exc}"

    if not rows:
        return "Query returned no rows."

    header = list(rows[0].keys())
    lines = [" | ".join(header)]
    for row in rows:
        lines.append(" | ".join(str(row[col]) for col in header))
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
