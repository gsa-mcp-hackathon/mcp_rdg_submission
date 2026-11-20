"""MCP tools for discovering, searching, and summarizing obligations."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from database import _query
from obligation_queries import _aggregate_obligations, _build_filters, _check_limit
from settings import CategoryColumn, ROW_ID_EXPR, SortOrder, TABLE, _ORDER_SQL


def describe_obligations_table() -> dict[str, Any]:
    """Describe the pfd_obligations table: columns, types, comments and total row count."""
    columns = [
        {"name": r.get("col_name"), "type": r.get("data_type"), "comment": r.get("comment")}
        for r in _query(f"DESCRIBE TABLE {TABLE}")
        if r.get("col_name") and not str(r.get("col_name")).startswith("#")
    ]
    stats = _query(
        f"SELECT count(*) AS row_count, min(obl_fscl_yr) AS min_fiscal_year, "
        f"max(obl_fscl_yr) AS max_fiscal_year, sum(obl_amt) AS total_obl_amt FROM {TABLE}"
    )[0]
    return {"table": TABLE, "columns": columns, **stats}


def list_distinct_values(column: CategoryColumn, limit: int = 100) -> list[dict[str, Any]]:
    """List distinct values of a categorical column with row counts and total obligation dollars.

    Use this to discover valid values for filters (states, program areas, investment types, ...).
    """
    limit = _check_limit(limit, 500)
    return _query(
        f"SELECT {column} AS value, count(*) AS row_count, sum(obl_amt) AS total_obl_amt "
        f"FROM {TABLE} GROUP BY 1 ORDER BY row_count DESC LIMIT {limit}"
    )


def search_obligations(
    fiscal_year: int | None = None,
    state: str | None = None,
    program_area: str | None = None,
    program_label: str | None = None,
    investment_type: str | None = None,
    portfolio_group: str | None = None,
    county_fips: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    text: str | None = None,
    order_by: SortOrder = "obl_amt_desc",
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    """Search obligation rows with optional filters and paging.

    Filters: fiscal_year (e.g. 2024), state (2-letter abbreviation, e.g. 'IA'), program_area
    (e.g. 'Single Family Housing'), program_label, investment_type (e.g. 'Grant Funds'),
    portfolio_group ('Residential' or 'Commercial'), county_fips (5-digit), min_amount /
    max_amount on obl_amt, and text (matches project name, recipient, lender or description).
    Returns at most 200 rows per call; each row has a row_id usable with get_obligation.
    """
    limit = _check_limit(limit)
    if offset < 0:
        raise ValueError("offset must be >= 0")
    where, params = _build_filters(
        fiscal_year, state, program_area, program_label, investment_type,
        portfolio_group, county_fips, min_amount, max_amount, text,
    )
    rows = _query(
        f"WITH t AS (SELECT {ROW_ID_EXPR} AS row_id, * FROM {TABLE} {where}) "
        f"SELECT *, count(*) OVER () AS _total_matches FROM t "
        f"ORDER BY {_ORDER_SQL[order_by]}, row_id LIMIT {limit} OFFSET {int(offset)}",
        params,
    )
    total = (
        rows[0].pop("_total_matches")
        if rows
        else _query(
            f"SELECT count(*) AS total_matches FROM {TABLE} {where}", params
        )[0]["total_matches"]
    )
    for r in rows[1:]:
        r.pop("_total_matches", None)
    return {"items": rows, "total_matches": total, "limit": limit, "offset": int(offset)}


def get_obligation(row_id: str) -> dict[str, Any]:
    """Get a single obligation row by the row_id returned from search_obligations."""
    rows = _query(
        f"WITH t AS (SELECT {ROW_ID_EXPR} AS row_id, * FROM {TABLE}) "
        "SELECT *, count(*) OVER () AS _duplicate_rows FROM t WHERE row_id = :row_id LIMIT 1",
        {"row_id": row_id.strip().lower()},
    )
    if not rows:
        raise ValueError(f"No obligation found with row_id {row_id!r}")
    # Identical duplicate rows share a row_id; report how many.
    duplicate_rows = rows[0].pop("_duplicate_rows")
    return {**rows[0], "duplicate_rows": duplicate_rows}


def summarize_obligations(
    group_by: list[CategoryColumn] | None = None,
    fiscal_year: int | None = None,
    state: str | None = None,
    program_area: str | None = None,
    program_label: str | None = None,
    investment_type: str | None = None,
    portfolio_group: str | None = None,
    county_fips: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    text: str | None = None,
    sort: Literal["total_obl_amt", "total_obl_counts", "group"] = "total_obl_amt",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Aggregate obligations: total dollars (sum obl_amt), total counts (sum obl_counts) and rows.

    group_by takes up to 3 columns, e.g. ['obl_fscl_yr'] or ['programarea', 'investment_type'].
    Leave it empty for overall totals. Accepts the same filters as search_obligations.
    """
    limit = _check_limit(limit, 500)
    cols = list(dict.fromkeys(group_by or []))
    if len(cols) > 3:
        raise ValueError("group_by supports at most 3 columns")
    where, params = _build_filters(
        fiscal_year, state, program_area, program_label, investment_type,
        portfolio_group, county_fips, min_amount, max_amount, text,
    )
    select_cols = ", ".join(cols) + ", " if cols else ""
    group_sql = f"GROUP BY {', '.join(cols)}" if cols else ""
    if sort == "group" and cols:
        order_sql = f"ORDER BY {', '.join(cols)}"
    elif sort == "total_obl_counts":
        order_sql = "ORDER BY total_obl_counts DESC"
    else:
        order_sql = "ORDER BY total_obl_amt DESC"
    return _query(
        f"SELECT {select_cols}sum(obl_amt) AS total_obl_amt, sum(obl_counts) AS total_obl_counts, "
        f"count(*) AS row_count FROM {TABLE} {where} {group_sql} {order_sql} LIMIT {limit}",
        params,
    )


def summarize_pfd_obligations_by_state(
    fiscal_year: int | None = None,
    state: str | None = None,
    county_fips: str | None = None,
    program_area: str | None = None,
    investment_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
    sort: Literal["amount_desc", "group_asc"] = "amount_desc",
) -> dict[str, Any]:
    """Summarize obligation dollars by fiscal year and state, highest amounts first by default."""
    return _aggregate_obligations(
        select_sql=(
            "obl_fscl_yr AS fiscal_year, obligation_state_abr AS state, "
            "SUM(obl_amt) AS total_obligation_amount, COUNT(*) AS source_row_count"
        ),
        group_by="obl_fscl_yr, obligation_state_abr",
        fiscal_year=fiscal_year,
        state=state,
        county_fips=county_fips,
        program_area=program_area,
        investment_type=investment_type,
        limit=limit,
        offset=offset,
        sort=sort,
    )


def summarize_pfd_obligations_by_program(
    fiscal_year: int | None = None,
    state: str | None = None,
    county_fips: str | None = None,
    program_area: str | None = None,
    investment_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
    sort: Literal["amount_desc", "group_asc"] = "amount_desc",
) -> dict[str, Any]:
    """Summarize obligation dollars by fiscal year and program area, with optional filters."""
    return _aggregate_obligations(
        select_sql=(
            "obl_fscl_yr AS fiscal_year, programarea AS program_area, "
            "SUM(obl_amt) AS total_obligation_amount, COUNT(*) AS source_row_count"
        ),
        group_by="obl_fscl_yr, programarea",
        fiscal_year=fiscal_year,
        state=state,
        county_fips=county_fips,
        program_area=program_area,
        investment_type=investment_type,
        limit=limit,
        offset=offset,
        sort=sort,
    )


def summarize_pfd_obligations_by_naics(
    fiscal_year: int | None = None,
    state: str | None = None,
    county_fips: str | None = None,
    program_area: str | None = None,
    investment_type: str | None = None,
    naics_industry_sector: str | None = None,
    limit: int = 100,
    offset: int = 0,
    sort: Literal["amount_desc", "group_asc"] = "amount_desc",
) -> dict[str, Any]:
    """Summarize obligation dollars by fiscal year and NAICS sector, with optional filters."""
    return _aggregate_obligations(
        select_sql=(
            "obl_fscl_yr AS fiscal_year, naics_industry_sector, "
            "SUM(obl_amt) AS total_obligation_amount, COUNT(*) AS source_row_count"
        ),
        group_by="obl_fscl_yr, naics_industry_sector",
        fiscal_year=fiscal_year,
        state=state,
        county_fips=county_fips,
        program_area=program_area,
        investment_type=investment_type,
        naics_industry_sector=naics_industry_sector,
        limit=limit,
        offset=offset,
        sort=sort,
    )


def summarize_pfd_obligations_by_state_and_naics(
    fiscal_year: int | None = None,
    state: str | None = None,
    county_fips: str | None = None,
    naics_industry_sector: str | None = None,
    program_area: str | None = None,
    investment_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
    sort: Literal["amount_desc", "group_asc"] = "amount_desc",
) -> dict[str, Any]:
    """Summarize obligation dollars by fiscal year, state, and NAICS sector."""
    return _aggregate_obligations(
        select_sql=(
            "obl_fscl_yr AS fiscal_year, obligation_state_abr AS state, "
            "naics_industry_sector, SUM(obl_amt) AS total_obligation_amount, "
            "COUNT(*) AS source_row_count"
        ),
        group_by="obl_fscl_yr, obligation_state_abr, naics_industry_sector",
        fiscal_year=fiscal_year,
        state=state,
        county_fips=county_fips,
        program_area=program_area,
        investment_type=investment_type,
        naics_industry_sector=naics_industry_sector,
        limit=limit,
        offset=offset,
        sort=sort,
    )


def summarize_pfd_obligations_by_state_and_county(
    fiscal_year: int | None = None,
    state: str | None = None,
    county_fips: str | None = None,
    naics_industry_sector: str | None = None,
    program_area: str | None = None,
    investment_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
    sort: Literal["amount_desc", "group_asc"] = "amount_desc",
) -> dict[str, Any]:
    """Summarize obligation dollars by fiscal year, state, and county."""
    return _aggregate_obligations(
        select_sql=(
            "obl_fscl_yr AS fiscal_year, obligation_state_abr AS state, "
            "obligation_county_fips, obligation_county_name, "
            "SUM(obl_amt) AS total_obligation_amount, COUNT(*) AS source_row_count"
        ),
        group_by=(
            "obl_fscl_yr, obligation_state_abr, obligation_county_fips, "
            "obligation_county_name"
        ),
        fiscal_year=fiscal_year,
        state=state,
        county_fips=county_fips,
        program_area=program_area,
        investment_type=investment_type,
        naics_industry_sector=naics_industry_sector,
        limit=limit,
        offset=offset,
        sort=sort,
    )


def register_tools(mcp: FastMCP) -> None:
    mcp.tool()(describe_obligations_table)
    mcp.tool()(list_distinct_values)
    mcp.tool()(search_obligations)
    mcp.tool()(get_obligation)
    mcp.tool()(summarize_obligations)
    mcp.tool()(summarize_pfd_obligations_by_state)
    mcp.tool()(summarize_pfd_obligations_by_program)
    mcp.tool()(summarize_pfd_obligations_by_naics)
    mcp.tool()(summarize_pfd_obligations_by_state_and_naics)
    mcp.tool()(summarize_pfd_obligations_by_state_and_county)
