"""Renders a compact schema description that's appended to every prompt."""
from __future__ import annotations

import sqlite3
from functools import lru_cache


@lru_cache(maxsize=8)
def get_schema_description(db_path: str) -> str:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [r[0] for r in cur.fetchall()]
        lines = []
        for t in tables:
            cur.execute(f'PRAGMA table_info("{t}")')
            cols = [row[1] for row in cur.fetchall()]
            lines.append(f"- {t}({', '.join(cols)})")
        return "\n".join(lines)
    finally:
        con.close()
