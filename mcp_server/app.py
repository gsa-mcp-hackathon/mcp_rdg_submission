"""Databricks Apps MCP entry point with streamable HTTP at /mcp."""

from __future__ import annotations

import logging
import os

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

import exposure
import fema
import obligation_tools
import helpers
from settings import TABLE


logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pfd_mcp")


mcp = FastMCP(
    "PFD Obligations",
    instructions=(
        "Read-only tools over USDA Rural Development obligations "
        f"({TABLE}, about 579K rows, fiscal years 2017-2027). Each row is an aggregate of "
        "obligations (obl_amt dollars, obl_counts count) for a fiscal year, location, "
        "program and recipient. Use list_distinct_values to discover valid filter values, "
        "the summarize_pfd_obligations_by_* tools for common state, program, NAICS, and "
        "county breakdowns, summarize_obligations for custom groupings, and "
        "search_obligations for row-level detail."
    ),
    host=os.environ.get("MCP_HOST", "0.0.0.0"),
    port=int(os.environ.get("DATABRICKS_APP_PORT", "8000")),
    stateless_http=True,
    json_response=True,
)


@mcp.custom_route("/", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "mcp_endpoint": "/mcp", "table": TABLE})


obligation_tools.register_tools(mcp)
fema.register_tools(mcp)
exposure.register_tools(mcp)
helpers.register_tools(mcp)


if __name__ == "__main__":
    log.info("Starting PFD Obligations MCP server on port %s", mcp.settings.port)
    mcp.run(transport="streamable-http")
