"""Read-only DuckDB access for the API.

Connections are short-lived (open per call, close immediately): DuckDB allows
many concurrent readers OR one writer, so holding a long-lived read connection
would block the hourly dbt rebuild. A dbt write can still collide with an
in-flight request for a moment — the pipeline retries next run, the API request
just sees the previous file state.

DUCKDB_PATH points at the warehouse file; the local default matches ml/data.py.
"""

from __future__ import annotations

import json
import os

LOCAL_DEFAULT = "de/dbt/ml_underground/ML_UNDERGROUND.duckdb"

# Columns stored as JSON text in the marts; parsed before returning to clients.
_JSON_FIELDS = {"target_modules", "param_sources", "topics", "tags", "dependencies"}


def warehouse_path() -> str:
    return os.getenv("DUCKDB_PATH", LOCAL_DEFAULT)


def warehouse_available() -> bool:
    return os.path.exists(warehouse_path())


def query(sql: str, params: tuple | list = ()) -> list[dict]:
    """Run one read-only query, return rows as dicts with lower-case keys."""
    import duckdb
    con = duckdb.connect(warehouse_path(), read_only=True)
    try:
        cur = con.execute(sql, list(params))
        cols = [d[0].lower() for d in cur.description]
        return [_coerce(dict(zip(cols, row))) for row in cur.fetchall()]
    finally:
        con.close()


def scalar(sql: str, params: tuple | list = ()):
    """Run a single-value query (e.g. COUNT(*)), return that value or None."""
    import duckdb
    con = duckdb.connect(warehouse_path(), read_only=True)
    try:
        row = con.execute(sql, list(params)).fetchone()
        return row[0] if row else None
    finally:
        con.close()


def _coerce(row: dict) -> dict:
    for key, value in row.items():
        if key in _JSON_FIELDS and isinstance(value, str):
            try:
                row[key] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                pass
        elif hasattr(value, "isoformat"):
            row[key] = value.isoformat()
    return row


def envelope(items: list, total: int, limit: int, offset: int) -> dict:
    return {"items": items, "total": int(total), "limit": limit, "offset": offset}
