"""Historical obligation exposure calculations for FEMA-designated areas."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from fema import get_disaster_areas, make_county_fips
from obligation_queries import _get_obligation_county_detail, _get_obligation_total


LOAN_TYPES: tuple[str, ...] = (
    "Loan Funds - Guaranteed",
    "Loan Funds - Direct",
)


def calculate_fema_investment_exposure(
    *,
    disaster_number: int,
    state: str,
    fiscal_year: int | None = None,
    program_area: str | None = None,
    portfolio_group: str = "Commercial",
    include_county_detail: bool = True,
) -> dict[str, Any]:

    state = state.strip().upper()
    if len(state) != 2 or not state.isalpha():
        raise ValueError("state must be a two-letter abbreviation, such as SD")
    if disaster_number <= 0:
        raise ValueError("disaster_number must be a positive integer")
    if portfolio_group not in {"Residential", "Commercial"}:
        raise ValueError("portfolio_group must be Residential or Commercial")

    investment_types = list(LOAN_TYPES) # only loans

    areas, fema_areas_url  = get_disaster_areas(
        disaster_number=disaster_number,
        state=state,
    )

    county_fips = make_county_fips(areas)
    statewide_designation = areas["designatedArea"].fillna("").str.strip().str.casefold().eq("statewide").any()
    if not county_fips and not statewide_designation:
        raise ValueError(
            "FEMA returned no county FIPS codes for this disaster and state; "
            "cannot calculate county-level exposure."
        )
    exposure_fips = None if statewide_designation else county_fips

    statewide = _get_obligation_total(
        fiscal_year=fiscal_year,
        state=state,
        county_fips=None,
        program_area=program_area,
        investment_types=investment_types,
        portfolio_group=portfolio_group,
    )

    fema_area = _get_obligation_total(
        fiscal_year=fiscal_year,
        state=state,
        county_fips=exposure_fips,
        program_area=program_area,
        investment_types=investment_types,
        portfolio_group=portfolio_group,
    )

    statewide_total = statewide["total_obligation_amount"]
    fema_area_total = fema_area["total_obligation_amount"]

    share = (
        fema_area_total / statewide_total
        if statewide_total
        else None
    )

    result = {
        "disaster_number": disaster_number,
        "state": state,
        "fiscal_year": fiscal_year,
        "program_area": program_area,
        "investment_types": investment_types,
        "portfolio_group": portfolio_group,
        "fema_county_fips": county_fips,
        "includes_statewide_designation": statewide_designation,
        "statewide_total_obligation_amount": statewide_total,
        "fema_area_total_obligation_amount": fema_area_total,
        "fema_area_share_of_statewide_obligations": share,
        "statewide_source_row_count": statewide["source_row_count"],
        "fema_area_source_row_count": fema_area["source_row_count"],
        "sources": { # required by FEMA API terms
            "fema_designated_areas_api_url": fema_areas_url,
            "fema_attribution_text": (
                "FEMA designated-area data source: "
                f"{fema_areas_url}"
            ),
        },
    }

    if include_county_detail and not statewide_designation:
        result["county_detail"] = _get_obligation_county_detail(
            fiscal_year=fiscal_year,
            state=state,
            county_fips=county_fips,
            program_area=program_area,
            investment_types=investment_types,
            portfolio_group=portfolio_group,
        )
    return result


def assess_investment_exposure_to_fema_areas(
    disaster_number: int,
    state: str,
    portfolio_group: Literal["Residential", "Commercial"],
    fiscal_year: int | None = None,
    include_county_detail: bool = True,
) -> dict:
    """
    Compare qualifying investments in the FEMA-designated counties of a
    confirmed disaster with the full qualifying investment population in
    the same state.

    Call search_fema_disasters first when the user has not supplied a
    FEMA disaster number. If search returns multiple candidates, ask the
    user to select or confirm one before calling this tool.

    The result is an exposure proxy based on historical obligation amounts.
    It does not represent unpaid principal, current balances, physical
    damage, or actual loss.

    For investment exposure, we are only looking at Loans, not Grants, 
    loans have investment_types of "Loan Funds - Guaranteed" or
    "Loan Funds - Direct"
    When presenting FEMA-derived results, include the complete URL in
    sources.fema_designated_areas_api_url.
    """

    return calculate_fema_investment_exposure(
        disaster_number=disaster_number,
        state=state,
        portfolio_group=portfolio_group,
        fiscal_year=fiscal_year,
        include_county_detail=include_county_detail,
    )


def register_tools(mcp: FastMCP) -> None:
    mcp.tool()(assess_investment_exposure_to_fema_areas)
