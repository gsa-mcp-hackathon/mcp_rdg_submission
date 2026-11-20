"""MCP tools for discovering and previewing Rural Data Gateway data."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import Settings
from .databricks import DatabricksGateway

mcp = FastMCP("Rural Data Gateway")


@lru_cache(maxsize=1)
def _gateway() -> DatabricksGateway:
    return DatabricksGateway(Settings.from_env())


def list_catalogs() -> list[dict[str, Any]]:
    """List the Databricks catalogs available to the configured identity."""
    return _gateway().list_catalogs()


def list_schemas(catalog: str) -> list[dict[str, Any]]:
    """List schemas in a Databricks catalog."""
    return _gateway().list_schemas(catalog)


def list_tables(catalog: str, schema: str) -> list[dict[str, Any]]:
    """List tables in a Databricks catalog and schema."""
    return _gateway().list_tables(catalog, schema)


def describe_table(
    catalog: str, schema: str, table: str
) -> list[dict[str, Any]]:
    """Return column metadata for a Databricks table."""
    return _gateway().describe_table(catalog, schema, table)


def preview_table(
    catalog: str, schema: str, table: str, limit: int = 20
) -> list[dict[str, Any]]:
    """Return a limited preview of rows from a Databricks table."""
    return _gateway().preview_table(catalog, schema, table, limit)


for tool in (list_catalogs, list_schemas, list_tables, describe_table, preview_table):
    mcp.tool()(tool)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

