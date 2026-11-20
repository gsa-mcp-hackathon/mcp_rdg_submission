"""Small read-only interface to a Databricks SQL warehouse."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from databricks import sql

from .config import Settings


def quote_identifier(value: str) -> str:
    if not value or "\x00" in value:
        raise ValueError("Databricks identifiers cannot be empty or contain null bytes")
    return f"`{value.replace('`', '``')}`"


def _serializable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (list, tuple)):
        return [_serializable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serializable(item) for key, item in value.items()}
    return str(value)


class DatabricksGateway:
    def __init__(
        self,
        settings: Settings,
        connect: Callable[..., Any] = sql.connect,
    ) -> None:
        self._settings = settings
        self._connect = connect

    def _execute(self, statement: str) -> list[dict[str, Any]]:
        with closing(
            self._connect(
                server_hostname=self._settings.server_hostname,
                http_path=self._settings.http_path,
                access_token=self._settings.access_token,
            )
        ) as connection:
            with closing(connection.cursor()) as cursor:
                cursor.execute(statement)
                columns = [column[0] for column in (cursor.description or ())]
                return [
                    {
                        column: _serializable(value)
                        for column, value in zip(columns, row, strict=True)
                    }
                    for row in cursor.fetchall()
                ]

    def list_catalogs(self) -> list[dict[str, Any]]:
        return self._execute("SHOW CATALOGS")

    def list_schemas(self, catalog: str) -> list[dict[str, Any]]:
        return self._execute(f"SHOW SCHEMAS IN {quote_identifier(catalog)}")

    def list_tables(self, catalog: str, schema: str) -> list[dict[str, Any]]:
        namespace = f"{quote_identifier(catalog)}.{quote_identifier(schema)}"
        return self._execute(f"SHOW TABLES IN {namespace}")

    def describe_table(
        self, catalog: str, schema: str, table: str
    ) -> list[dict[str, Any]]:
        table_name = ".".join(
            quote_identifier(part) for part in (catalog, schema, table)
        )
        return self._execute(f"DESCRIBE TABLE {table_name}")

    def preview_table(
        self, catalog: str, schema: str, table: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= self._settings.max_preview_rows:
            raise ValueError(
                f"limit must be between 1 and {self._settings.max_preview_rows}"
            )
        table_name = ".".join(
            quote_identifier(part) for part in (catalog, schema, table)
        )
        return self._execute(f"SELECT * FROM {table_name} LIMIT {limit}")

