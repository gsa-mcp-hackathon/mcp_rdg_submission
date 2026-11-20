# API README

This API is intended only to support the MCP Test. It is built with fast api on two tables:

- `rd_edapt.analytics_bronze.pfd_obligations`
- `rd_edapt.analytics_bronze.pfd_loans_commercial_guaranteed`

These tables were selected because they are the foundation for much of what is published on the Rural Data Gateway. They were last updated 2026-10-28, manually, and are not expected to be updated or maintained.

These tables are within databricks which has a built in sql mcp server, but we are trying to be prepared for transport.

## How to use

### Endpoints

All endpoints are read-only `GET`s. Interactive docs are at `/docs` (Swagger) and `/redoc`;
`GET /` is a health check.

| Endpoint | Filters (all optional) | Notes |
| --- | --- | --- |
| `/pfd_obligations` | `fiscal_year`, `state`, `county_fips`, `program_area`, `investment_type` | About 579K rows. Each row is an aggregate: `obl_amt` dollars, `obl_counts` obligations |
| `/pfd_loans_commercial_guaranteed` | `state` (`loan_state_abr`), `program_area`, `close_fiscal_year`, `delinquent` (true/false) | About 3.3K loans, ordered by `loan_id` |
| `/pfd_loans_commercial_guaranteed/{loan_id}` | none | One loan; returns 404 if not found |

List endpoints take `limit` (1-1000, default 100) and `offset` (default 0) and return
`{"items": [...], "total": <matching rows>, "limit": ..., "offset": ...}`. Text filters
ignore case. `close_fiscal_year` is stored as text in the source table (for example `2021`).

Examples:

```powershell
/pfd_obligations?fiscal_year=2024&state=IA&limit=50
/pfd_loans_commercial_guaranteed?program_area=Business%20Programs&delinquent=true
/pfd_loans_commercial_guaranteed/187015268
```

### Deploy as a Databricks App

1. Create an app (for example `pfd-api`) and add a SQL warehouse resource with the key
   `sql-warehouse` (`CAN_USE`). `app.yaml` passes it to the app as `DATABRICKS_WAREHOUSE_ID`.
2. Grant the app's service principal `SELECT` on both tables (plus `USE CATALOG` and
   `USE SCHEMA` on `rd_edapt.analytics_bronze`).
3. Deploy from this folder:

   ```bash
   databricks apps deploy "$API_APP_NAME" --source-code-path /Workspace/<repo-path>/api
   ```

   Set `API_APP_NAME` privately to the name of the app you created.

App callers must authenticate to Databricks; for example, send a workspace OAuth token as
`Authorization: Bearer <token>`.

### Run locally

From this folder, with Databricks credentials available through a CLI profile or
`DATABRICKS_HOST` and `DATABRICKS_TOKEN`:

```bash
pip install -r requirements.txt
export DATABRICKS_WAREHOUSE_ID=<warehouse-id>
python api_server.py   # serves on http://localhost:8000
```

### Files

- `api_server.py`: FastAPI app and routes; all filters are bound as SQL parameters.
- `models.py`: Pydantic response models matching the source table schemas.
