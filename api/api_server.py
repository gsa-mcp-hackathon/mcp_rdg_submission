"""Read-only REST API over two Rural Data Gateway tables in rd_edapt.analytics_bronze.

Runs on Databricks Apps (or locally with uvicorn). Queries run on the SQL warehouse attached as
the app resource `sql-warehouse` and authenticate as the app's service principal; locally they
use your Databricks CLI profile or DATABRICKS_* environment variables.

All filters are bound as SQL parameters; limit/offset are validated integers.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

from databricks import sql
from databricks.sdk.core import Config
from fastapi import FastAPI, HTTPException, Query

try:  # imported as part of the `api` package
    from .models import (
        PfdLoanCommercialGuaranteed, PfdLoanCommercialGuaranteedPage,
        PfdObligation, PfdObligationPage,
        PfdStateAggregate, PfdStateAggregatePage,
        PfdNaicsAggregate, PfdNaicsAggregatePage,
        PfdStateNaicsAggregate, PfdStateNaicsAggregatePage,
        PfdProgramAggregate, PfdProgramAggregatePage,
        PfdStateCountyAggregate, PfdStateCountyAggregatePage
    )
except ImportError:  # run from inside api/ (Databricks Apps, `uvicorn api_server:app`)
    from models import (
        PfdLoanCommercialGuaranteed, PfdLoanCommercialGuaranteedPage,
        PfdObligation, PfdObligationPage,
        PfdStateAggregate, PfdStateAggregatePage,
        PfdNaicsAggregate, PfdNaicsAggregatePage,
        PfdStateNaicsAggregate, PfdStateNaicsAggregatePage,
        PfdProgramAggregate, PfdProgramAggregatePage,
        PfdStateCountyAggregate, PfdStateCountyAggregatePage
    )

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pfd_api")

SCHEMA = "rd_edapt.analytics_bronze"
OBLIGATIONS = f"{SCHEMA}.pfd_obligations"
LOANS = f"{SCHEMA}.pfd_loans_commercial_guaranteed"
MAX_LIMIT = 1000

app = FastAPI(
    title="RDG Portable Table API",
    description="Read-only access to PFD obligations and commercial guaranteed loans.",
    version="0.2.0",
)


# ---------------------------------------------------------------------------
# Databricks SQL access
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _cfg() -> Config:
    # On Apps, DATABRICKS_HOST / CLIENT_ID / CLIENT_SECRET for the service principal are injected.
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


def run_query(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    cfg = _cfg()
    with sql.connect(
        server_hostname=_hostname(),
        http_path=_http_path(),
        credentials_provider=lambda: cfg.authenticate,
    ) as conn, conn.cursor() as cur:
        cur.execute(query, params or {})
        return cur.fetchall_arrow().to_pylist()


def _where(filters: list[tuple[str, str, Any]]) -> tuple[str, dict[str, Any]]:
    """Build a WHERE clause from (sql_condition, param_name, value), skipping None values."""
    clauses, params = [], {}
    for condition, name, value in filters:
        if value is not None and value != "":
            clauses.append(condition)
            params[name] = value
    return (("WHERE " + " AND ".join(clauses)) if clauses else ""), params

# this is my generic aggregate helper for defined aggregations in models
def _pfd_where(
    fiscal_year: int | None,
    state: str | None,
    county_fips: str | None,
    program_area: str | None,
    investment_type: str | None,
    naics_industry_sector: str | None = None,
) -> tuple[str, dict[str, Any]]:
    return _where([
        ("obl_fscl_yr = :fiscal_year", "fiscal_year", fiscal_year),
        ("upper(obligation_state_abr) = upper(:state)", "state", state),
        ("obligation_county_fips = :county_fips", "county_fips", county_fips),
        ("lower(programarea) = lower(:program_area)", "program_area", program_area),
        (
            "lower(investment_type) = lower(:investment_type)",
            "investment_type",
            investment_type,
        ),
        ("naics_industry_sector = :naics_industry_sector", "naics_industry_sector", naics_industry_sector),
    ])


def _page(table: str, where: str, params: dict[str, Any], order_by: str, limit: int, offset: int):
    """Return (rows, total_matches) for one page of a filtered table."""
    q = (
        f"SELECT *, count(*) OVER () AS _total_matches FROM {table} {where} "
        f"ORDER BY {order_by} LIMIT {int(limit)} OFFSET {int(offset)}"
    )
    try:
        rows = run_query(q, params)
        total = (
            rows[0]["_total_matches"]
            if rows
            else run_query(
                f"SELECT count(*) AS total_matches FROM {table} {where}", params
            )[0]["total_matches"]
        )
    except Exception:
        log.exception("Query failed on %s", table)
        raise HTTPException(502, "Database query failed")
    for r in rows:
        r.pop("_total_matches", None)
    return rows, total

def _aggregate_page(
    table: str,
    where: str,
    params: dict[str, Any],
    select_sql: str,
    group_by: str,
    order_by: str,
    limit: int,
    offset: int,
):
    """
    Return (rows, total_groups) for one page of grouped results.

    select_sql, group_by, order_by, and table must come from trusted
    application constants—not directly from request parameters.
    """
    query = f"""
        SELECT
            {select_sql},
            COUNT(*) OVER () AS _total_groups
        FROM {table}
        {where}
        GROUP BY {group_by}
        ORDER BY {order_by}
        LIMIT {int(limit)}
        OFFSET {int(offset)}
    """

    try:
        rows = run_query(query, params)

        if rows:
            total = rows[0]["_total_groups"]
        else:
            count_query = f"""
                SELECT COUNT(*) AS total_groups
                FROM (
                    SELECT {group_by}
                    FROM {table}
                    {where}
                    GROUP BY {group_by}
                ) grouped_results
            """
            total = run_query(count_query, params)[0]["total_groups"]

    except Exception:
        log.exception("Aggregate query failed on %s", table)
        raise HTTPException(502, "Database query failed")

    for row in rows:
        row.pop("_total_groups", None)

    return rows, total

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
def health() -> dict[str, Any]:
    return {"status": "ok", "docs": "/docs", "tables": [OBLIGATIONS, LOANS]}


@app.get("/pfd_obligations", response_model=PfdObligationPage)
def list_pfd_obligations(
    fiscal_year: int | None = Query(None, description="obl_fscl_yr, e.g. 2024"),
    state: str | None = Query(None, description="2-letter state abbreviation, e.g. IA"),
    county_fips: str | None = Query(None, description="5-digit county FIPS"),
    program_area: str | None = Query(None, description="programarea, e.g. Single Family Housing"),
    investment_type: str | None = Query(None, description="e.g. Grant Funds"),
    limit: int = Query(100, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    """Page through PFD obligation rows (aggregated obligations by year, place, program, recipient)."""
    where, params = _where([
        ("obl_fscl_yr = :fiscal_year", "fiscal_year", fiscal_year),
        ("upper(obligation_state_abr) = upper(:state)", "state", state),
        ("obligation_county_fips = :county_fips", "county_fips", county_fips),
        ("lower(programarea) = lower(:program_area)", "program_area", program_area),
        ("lower(investment_type) = lower(:investment_type)", "investment_type", investment_type),
    ])
    rows, total = _page(
        OBLIGATIONS, where, params,
        # No primary key: sort on the descriptive columns so pages are stable.
        "obl_fscl_yr, obligation_state_abr, obligation_county_fips, programarea, programlabel, "
        "fundingcode, prj_nm, borr_full_nm_pii_safe, obl_amt",
        limit, offset,
    )
    return {"items": [PfdObligation.model_validate(r) for r in rows],
            "total": total, "limit": limit, "offset": offset}

# define aggregations

# state
@app.get(
    "/pfd_obligations/aggregates/by-state",
    response_model=PfdStateAggregatePage,
)
def aggregate_pfd_obligations_by_state(
    fiscal_year: int | None = Query(None, description="Fiscal year, e.g. 2024"),
    state: str | None = Query(None, description="2-letter state abbreviation"),
    county_fips: str | None = Query(None, description="5-digit county FIPS"),
    program_area: str | None = Query(None),
    investment_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    """Return obligations grouped by fiscal year and state."""

    where, params = _pfd_where(
        fiscal_year=fiscal_year,
        state=state,
        county_fips=county_fips,
        program_area=program_area,
        investment_type=investment_type,
    )

    rows, total = _aggregate_page(
        table=OBLIGATIONS,
        where=where,
        params=params,
        select_sql="""
            obl_fscl_yr AS fiscal_year,
            obligation_state_abr AS state,
            SUM(obl_amt) AS total_obligation_amount,
            COUNT(*) AS source_row_count
        """,
        group_by="""
            obl_fscl_yr,
            obligation_state_abr
        """,
        order_by="""
            obl_fscl_yr,
            obligation_state_abr
        """,
        limit=limit,
        offset=offset,
    )

    return {
        "items": [PfdStateAggregate.model_validate(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }

# program
@app.get(
    "/pfd_obligations/aggregates/by-program",
    response_model=PfdProgramAggregatePage,
)
def aggregate_pfd_obligations_by_program(
    fiscal_year: int | None = Query(None, description="Fiscal year, e.g. 2024"),
    state: str | None = Query(None, description="2-letter state abbreviation"),
    county_fips: str | None = Query(None, description="5-digit county FIPS"),
    program_area: str | None = Query(None),
    investment_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    """Return obligations grouped by fiscal year and program_area."""

    where, params = _pfd_where(
        fiscal_year=fiscal_year,
        state=state,
        county_fips=county_fips,
        program_area=program_area,
        investment_type=investment_type,
    )

    rows, total = _aggregate_page(
        table=OBLIGATIONS,
        where=where,
        params=params,
        select_sql="""
            obl_fscl_yr AS fiscal_year,
            programarea AS program_area,
            SUM(obl_amt) AS total_obligation_amount,
            COUNT(*) AS source_row_count
        """,
        group_by="""
            obl_fscl_yr,
            programarea
        """,
        order_by="""
            obl_fscl_yr,
            programarea
        """,
        limit=limit,
        offset=offset,
    )

    return {
        "items": [PfdProgramAggregate.model_validate(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }

# naics
@app.get(
    "/pfd_obligations/aggregates/by-naics",
    response_model=PfdNaicsAggregatePage,
)

def aggregate_pfd_obligations_by_naics(
    fiscal_year: int | None = Query(None, description="Fiscal year, e.g. 2024"),
    state: str | None = Query(None, description="2-letter state abbreviation"),
    county_fips: str | None = Query(None, description="5-digit county FIPS"),
    program_area: str | None = Query(None, description = "Rural Development Program Area, e.g. Single Family Housing"),
    investment_type: str | None = Query(None, description = "Loan or Grant, Direct or Guaranteed"),
    naics_industry_sector: str | None = Query(None, description="Description of Industry Sector based on 2-digit NAICS"),
    limit: int = Query(100, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    """Return obligations grouped by fiscal year and NAICS code."""

    where, params = _pfd_where(
        fiscal_year=fiscal_year,
        state=state,
        county_fips=county_fips,
        program_area=program_area,
        investment_type=investment_type,
        naics_industry_sector=naics_industry_sector,
    )

    rows, total = _aggregate_page(
        table=OBLIGATIONS,
        where=where,
        params=params,
        select_sql="""
            obl_fscl_yr AS fiscal_year,
            naics_industry_sector,
            SUM(obl_amt) AS total_obligation_amount,
            COUNT(*) AS source_row_count
        """,
        group_by="""
            obl_fscl_yr,
            naics_industry_sector
        """,
        order_by="""
            obl_fscl_yr,
            naics_industry_sector
        """,
        limit=limit,
        offset=offset,
    )

    return {
        "items": [
            PfdNaicsAggregate.model_validate(row)
            for row in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }

# state AND naics
@app.get(
    "/pfd_obligations/aggregates/by-state-naics",
    response_model=PfdStateNaicsAggregatePage,
)

def aggregate_pfd_obligations_by_state_naics(
    fiscal_year: int | None = Query(None, description="Fiscal year, e.g. 2024"),
    state: str | None = Query(None, description="2-letter state abbreviation"),
    county_fips: str | None = Query(None, description="5-digit county FIPS"),
    program_area: str | None = Query(None, description = "Rural Development Program Area, e.g. Single Family Housing"),
    investment_type: str | None = Query(None, description = "Loan or Grant, Direct or Guaranteed"),
    naics_industry_sector: str | None = Query(None, description="Description of Industry Sector based on 2-digit NAICS"),
    limit: int = Query(100, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    """Return obligations grouped by fiscal year, state, and NAICS code."""

    where, params = _pfd_where(
        fiscal_year=fiscal_year,
        state=state,
        county_fips=county_fips,
        program_area=program_area,
        investment_type=investment_type,
        naics_industry_sector=naics_industry_sector,
    )

    rows, total = _aggregate_page(
        table=OBLIGATIONS,
        where=where,
        params=params,
        select_sql="""
            obl_fscl_yr AS fiscal_year,
            obligation_state_abr AS state,
            naics_industry_sector,
            SUM(obl_amt) AS total_obligation_amount,
            COUNT(*) AS source_row_count
        """,
        group_by="""
            obl_fscl_yr,
            obligation_state_abr,
            naics_industry_sector
        """,
        order_by="""
            obl_fscl_yr,
            obligation_state_abr,
            naics_industry_sector
        """,
        limit=limit,
        offset=offset,
    )

    return {
        "items": [
            PfdStateNaicsAggregate.model_validate(row)
            for row in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }

# state and county (we need this one for fema and for the county one)
@app.get(
    "/pfd_obligations/aggregates/by-state-county",
    response_model=PfdStateCountyAggregatePage,
)

def aggregate_pfd_obligations_by_state_county(
    fiscal_year: int | None = Query(None, description="Fiscal year, e.g. 2024"),
    state: str | None = Query(None, description="2-letter state abbreviation"),
    county_fips: str | None = Query(None, description="5-digit county FIPS"),
    program_area: str | None = Query(None, description = "Rural Development Program Area, e.g. Single Family Housing"),
    investment_type: str | None = Query(None, description = "Loan or Grant, Direct or Guaranteed"),
    naics_industry_sector: str | None = Query(None, description="Description of Industry Sector based on 2-digit NAICS"),
    limit: int = Query(100, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    """Return obligations grouped by fiscal year, state, and county."""

    where, params = _pfd_where(
        fiscal_year=fiscal_year,
        state=state,
        county_fips=county_fips,
        program_area=program_area,
        investment_type=investment_type,
        naics_industry_sector=naics_industry_sector,
    )

    rows, total = _aggregate_page(
        table=OBLIGATIONS,
        where=where,
        params=params,
        select_sql="""
            obl_fscl_yr AS fiscal_year,
            obligation_state_abr AS state,
            obligation_county_fips,
            obligation_county_name,
            SUM(obl_amt) AS total_obligation_amount,
            COUNT(*) AS source_row_count
        """,
        group_by="""
            obl_fscl_yr,
            obligation_state_abr,
            obligation_county_fips,
            obligation_county_name
        """,
        order_by="""
            obl_fscl_yr,
            obligation_state_abr,
            obligation_county_fips,
            obligation_county_name
        """,
        limit=limit,
        offset=offset,
    )

    return {
        "items": [
            PfdStateCountyAggregate.model_validate(row)
            for row in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


### loans -- not used right now?
@app.get("/pfd_loans_commercial_guaranteed", response_model=PfdLoanCommercialGuaranteedPage)
def list_loans(
    state: str | None = Query(None, description="loan_state_abr, 2-letter abbreviation"),
    program_area: str | None = Query(None, description="program_area"),
    close_fiscal_year: str | None = Query(None, description="clse_fscl_yr (stored as text), e.g. 2024"),
    delinquent: bool | None = Query(None, description="Filter on delinquent_indicator"),
    limit: int = Query(100, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    """Page through commercial guaranteed loans, ordered by loan_id."""
    where, params = _where([
        ("upper(loan_state_abr) = upper(:state)", "state", state),
        ("lower(program_area) = lower(:program_area)", "program_area", program_area),
        ("clse_fscl_yr = :close_fiscal_year", "close_fiscal_year", close_fiscal_year),
        ("delinquent_indicator = :delinquent", "delinquent",
         None if delinquent is None else int(delinquent)),
    ])
    rows, total = _page(LOANS, where, params, "loan_id", limit, offset)
    return {"items": [PfdLoanCommercialGuaranteed.model_validate(r) for r in rows],
            "total": total, "limit": limit, "offset": offset}


@app.get("/pfd_loans_commercial_guaranteed/{loan_id}", response_model=PfdLoanCommercialGuaranteed)
def get_loan(loan_id: int):
    """Get one commercial guaranteed loan by loan_id (unique in the source table)."""
    rows, _ = _page(LOANS, "WHERE loan_id = :loan_id", {"loan_id": loan_id}, "loan_id", 1, 0)
    if not rows:
        raise HTTPException(404, f"No loan with loan_id {loan_id}")
    return PfdLoanCommercialGuaranteed.model_validate(rows[0])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("DATABRICKS_APP_PORT", "8000")))
