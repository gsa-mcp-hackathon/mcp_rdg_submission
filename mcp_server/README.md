# PFD Obligations MCP Server

This folder is a standalone Databricks App. Deploy the entire folder, not only
the entry point. The existing app configuration still runs `python app.py`.

## Modules

| File | Responsibility |
| --- | --- |
| [app.py](app.py) | Logging, FastMCP configuration, health route, tool registration, and startup |
| [settings.py](settings.py) | Table name, row ID expression, limits, allowed columns, and sort orders |
| [database.py](database.py) | Databricks authentication, connection handling, parameterized SQL execution, and result serialization |
| [obligation_queries.py](obligation_queries.py) | Shared filters, limit validation, aggregation, and exposure queries |
| [obligation_tools.py](obligation_tools.py) | Table discovery, row searches, row detail, and custom and predefined summaries |
| [fema.py](fema.py) | OpenFEMA requests, declaration searches, designated areas, and county FIPS normalization |
| [exposure.py](exposure.py) | Combining FEMA areas with historical obligation totals to assess exposure |

The entry point creates one FastMCP instance and passes it to each topic's
`register_tools(mcp)` function. Topic modules never import the entry point.
Tool functions remain ordinary module-level functions with explicit signatures
and docstrings. When adding a tool, define it in its topic module and add it to
that module's registration function.

Obligation tools use the shared query helpers and database access. FEMA lookups
do not depend on obligation queries. Exposure combines the two topics.
Sibling imports are resolved by running the entry point as a script, matching
the Databricks Apps launch command.

## Local Checks

From the repository root, install the app dependencies and run its tests:

```bash
python -m pip install -r mcp_server/requirements.txt
python -m unittest discover -s tests -p test_mcp_app.py -v
```

These tests mock Databricks SQL and FEMA HTTP requests. They do not need
credentials, a warehouse, or network access to those services.

To run the server locally, bind it explicitly to loopback.

Bash:

```bash
MCP_HOST=127.0.0.1 python mcp_server/app.py
```

PowerShell:

```powershell
$env:MCP_HOST = '127.0.0.1'
python mcp_server/app.py
```

The standalone server has no incoming authentication. Do not expose it to the
network: clients that can reach it can invoke tools using its configured
Databricks identity. Without `MCP_HOST`, the bind address defaults to `0.0.0.0`
for the hosted Databricks Apps deployment.

The default port is 8000, or `DATABRICKS_APP_PORT` when set. The health route is
`GET /`; the MCP endpoint is `/mcp`. Obligation tools require Databricks
authentication (a local CLI profile or the hosted app's service principal) and
`DATABRICKS_WAREHOUSE_ID`, as described in the
[repository README](../README.md).
