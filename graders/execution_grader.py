"""Execution-accuracy grader: runs the agent's SQL and the gold SQL read-only
and diffs the result sets.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass
class ExecutionResult:
    passed: bool
    error: Optional[str]
    agent_rows: Optional[list]
    gold_rows: Optional[list]


def _run_readonly(db_path: str, sql: str, limit_rows: int = 1000) -> list:
    """Run a single read-only statement, blocking anything but SELECT/WITH
    regardless of what the agent produced."""
    stripped = sql.strip().rstrip(";")
    if not stripped:
        raise ValueError("empty SQL")
    first_word = stripped.split(None, 1)[0].lower()
    if first_word not in ("select", "with"):
        raise ValueError(f"refusing to execute non-SELECT statement (starts with '{first_word}')")

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        con.execute("PRAGMA query_only = ON;")
        cur = con.execute(stripped)
        return cur.fetchmany(limit_rows)
    finally:
        con.close()


def _normalize(rows: list) -> list:
    return [tuple(round(v, 2) if isinstance(v, float) else v for v in row) for row in rows]


def grade_execution(db_path: str, agent_sql: Optional[str], gold_sql: str) -> ExecutionResult:
    try:
        gold_rows = _normalize(_run_readonly(db_path, gold_sql))
    except Exception as exc:  # gold SQL should never fail; surface loudly if it does
        return ExecutionResult(False, f"gold query failed: {exc}", None, None)

    if not agent_sql:
        return ExecutionResult(False, "agent produced no SQL (refused or unparsable response)", None, gold_rows)

    try:
        agent_rows = _normalize(_run_readonly(db_path, agent_sql))
    except Exception as exc:
        return ExecutionResult(False, f"agent query failed: {exc}", None, gold_rows)

    order_sensitive = "order by" in gold_sql.lower()
    if order_sensitive:
        passed = agent_rows == gold_rows
    else:
        passed = sorted(map(str, agent_rows)) == sorted(map(str, gold_rows))
    return ExecutionResult(passed, None if passed else "row mismatch", agent_rows, gold_rows)
