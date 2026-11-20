"""Shared parameterized filters and obligation aggregation queries."""

from __future__ import annotations

from typing import Any, Literal

from database import _query
from settings import MAX_LIMIT, TABLE


def _check_limit(limit: int, maximum: int = MAX_LIMIT) -> int:
    if not 1 <= int(limit) <= maximum:
        raise ValueError(f"limit must be between 1 and {maximum}")
    return int(limit)


def _build_filters(
    fiscal_year: int | None = None,
    state: str | None = None,
    program_area: str | None = None,
    program_label: str | None = None,
    investment_type: str | None = None,
    portfolio_group: str | None = None,
    county_fips: str | list[str] | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    text: str | None = None,
    naics_industry_sector: str | None = None,
    investment_types: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return a parameterized WHERE clause containing only the filters provided."""
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if fiscal_year is not None:
        clauses.append("obl_fscl_yr = :fiscal_year")
        params["fiscal_year"] = int(fiscal_year)
    if state:
        clauses.append("upper(obligation_state_abr) = upper(:state)")
        params["state"] = state.strip()
    if program_area:
        clauses.append("lower(programarea) = lower(:program_area)")
        params["program_area"] = program_area.strip()
    if program_label:
        clauses.append("lower(programlabel) = lower(:program_label)")
        params["program_label"] = program_label.strip()
    if investment_type:
        clauses.append("lower(investment_type) = lower(:investment_type)")
        params["investment_type"] = investment_type.strip()
    if portfolio_group:
        clauses.append("lower(portfolio_group) = lower(:portfolio_group)")
        params["portfolio_group"] = portfolio_group.strip()
    if isinstance(county_fips, str) and county_fips:
        clauses.append("obligation_county_fips = :county_fips")
        params["county_fips"] = county_fips.strip()
    elif county_fips is not None and not isinstance(county_fips, str):
        normalized_fips = list(dict.fromkeys(code.strip() for code in county_fips if code.strip()))
        if normalized_fips:
            names = [f"county_fips_{index}" for index in range(len(normalized_fips))]
            clauses.append(
                "obligation_county_fips IN (" + ", ".join(f":{name}" for name in names) + ")"
            )
            params.update(dict(zip(names, normalized_fips)))
        else:
            clauses.append("1 = 0")
    if investment_types is not None:
        normalized_types = list(dict.fromkeys(value.strip() for value in investment_types if value.strip()))
        if normalized_types:
            names = [f"investment_type_{index}" for index in range(len(normalized_types))]
            clauses.append(
                "lower(investment_type) IN ("
                + ", ".join(f"lower(:{name})" for name in names)
                + ")"
            )
            params.update(dict(zip(names, normalized_types)))
        else:
            clauses.append("1 = 0")
    if naics_industry_sector:
        clauses.append("naics_industry_sector = :naics_industry_sector")
        params["naics_industry_sector"] = naics_industry_sector.strip()
    if min_amount is not None:
        clauses.append("obl_amt >= :min_amount")
        params["min_amount"] = float(min_amount)
    if max_amount is not None:
        clauses.append("obl_amt <= :max_amount")
        params["max_amount"] = float(max_amount)
    if text:
        clauses.append(
            "(prj_nm ILIKE :text OR borr_full_nm_pii_safe ILIKE :text"
            " OR project_announced_description ILIKE :text OR lender_name ILIKE :text)"
        )
        params["text"] = f"%{text.strip()}%"
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def _aggregate_obligations(
    select_sql: str,
    group_by: str,
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
    """Return a page of a predefined aggregation and its total group count."""
    limit = _check_limit(limit, 1000)
    if offset < 0:
        raise ValueError("offset must be >= 0")

    where, params = _build_filters(
        fiscal_year=fiscal_year,
        state=state,
        program_area=program_area,
        investment_type=investment_type,
        county_fips=county_fips,
        naics_industry_sector=naics_industry_sector,
    )
    order_by = (
        f"total_obligation_amount DESC, {group_by}"
        if sort == "amount_desc"
        else group_by
    )
    rows = _query(
        f"SELECT {select_sql}, count(*) OVER () AS _total_groups "
        f"FROM {TABLE} {where} GROUP BY {group_by} "
        f"ORDER BY {order_by} LIMIT {limit} OFFSET {int(offset)}",
        params,
    )
    if rows:
        total = rows[0]["_total_groups"]
        for row in rows:
            row.pop("_total_groups", None)
    else:
        total = _query(
            f"SELECT count(*) AS total_groups FROM ("
            f"SELECT {group_by} FROM {TABLE} {where} GROUP BY {group_by}"
            ") grouped_results",
            params,
        )[0]["total_groups"]
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


def _get_obligation_total(
    *,
    fiscal_year: int | None,
    state: str,
    county_fips: list[str] | None,
    program_area: str | None,
    investment_types: list[str] | None,
    portfolio_group: str,
) -> dict[str, float | int]:
    where, params = _build_filters(
        fiscal_year=fiscal_year,
        state=state,
        county_fips=county_fips,
        program_area=program_area,
        investment_types=investment_types,
        portfolio_group=portfolio_group,
    )
    row = _query(
        f"SELECT COALESCE(SUM(obl_amt), 0) AS total_obligation_amount, "
        f"COUNT(*) AS source_row_count FROM {TABLE} {where}",
        params,
    )[0]

    return {
        "total_obligation_amount": float(
            row.get("total_obligation_amount") or 0
        ),
        "source_row_count": int(
            row.get("source_row_count") or 0
        ),
    }


def _get_obligation_county_detail(
    *,
    fiscal_year: int | None,
    state: str,
    county_fips: list[str],
    program_area: str | None,
    investment_types: list[str] | None,
    portfolio_group: str,
) -> list[dict[str, Any]]:
    where, params = _build_filters(
        fiscal_year=fiscal_year,
        state=state,
        county_fips=county_fips,
        program_area=program_area,
        investment_types=investment_types,
        portfolio_group=portfolio_group,
    )
    return _query(
        f"SELECT obligation_county_fips, obligation_county_name, "
        f"SUM(obl_amt) AS total_obligation_amount, COUNT(*) AS source_row_count "
        f"FROM {TABLE} {where} "
        "GROUP BY obligation_county_fips, obligation_county_name "
        "ORDER BY total_obligation_amount DESC, obligation_county_fips",
        params,
    )
