"""Databricks authentication, SQL execution, and JSON-compatible values."""

from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any

from databricks import sql
from databricks.sdk.core import Config


@lru_cache(maxsize=1)
def _cfg() -> Config:
    # Apps injects DATABRICKS_HOST / DATABRICKS_CLIENT_ID / DATABRICKS_CLIENT_SECRET for the SP.
    return Config()


def _hostname() -> str:
    host = _cfg().host or ""
    return host.replace("https://", "").replace("http://", "").rstrip("/")


def _http_path() -> str:
    warehouse_id = os.environ.get("DATABRICKS_WAREHOUSE_ID", "").strip()
    if not warehouse_id:
        raise RuntimeError(
            "DATABRICKS_WAREHOUSE_ID is not set; attach the SQL warehouse resource 'sql-warehouse'."
        )
    return f"/sql/1.0/warehouses/{warehouse_id}"


def _serializable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (list, tuple)):
        return [_serializable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _serializable(v) for k, v in value.items()}
    return str(value)


def _query(statement: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    cfg = _cfg()
    with sql.connect(
        server_hostname=_hostname(),
        http_path=_http_path(),
        credentials_provider=lambda: cfg.authenticate,
    ) as conn, conn.cursor() as cur:
        cur.execute(statement, params or {})
        columns = [d[0] for d in (cur.description or ())]
        return [
            {c: _serializable(v) for c, v in zip(columns, row)}
            for row in cur.fetchall()
        ]
