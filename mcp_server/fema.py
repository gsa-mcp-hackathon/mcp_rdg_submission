"""FEMA declaration lookups, county FIPS normalization, and MCP tools."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import requests
from mcp.server.fastmcp import FastMCP


FEMA_URL = (
    "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"
)

def _request_fema(
    params: dict[str, Any],
    timeout: int = 30,
) -> tuple[dict[str, Any], str]:
    response = requests.get(
        FEMA_URL,
        params=params,
        timeout=timeout,
    )
    response.raise_for_status()

    # to give the response.url for FEMA Terms & Conditions
    return response.json(), response.url


def get_fema_disasters(
    state: str,
    title_contains: str,
    incident_begin_date: str | date,
    incident_end_date: str | date,
    timeout: int = 30,
) -> tuple[pd.DataFrame, str]:
    """
    Query FEMA disaster declarations and return selected fields as a DataFrame.

    Parameters
    ----------
    state : str
        Two-letter state abbreviation, such as "SD".
    title_contains : str
        Text to search for in declarationTitle, such as "STORM".
    incident_begin_date : str or datetime.date
        Earliest incident begin date, formatted as YYYY-MM-DD.
    incident_end_date : str or datetime.date
        Latest incident end date, formatted as YYYY-MM-DD.
    timeout : int
        HTTP request timeout in seconds.

    Returns
    -------
    pandas.DataFrame
        Columns:
        disasterNumber, declarationTitle,
        incidentBeginDate, incidentEndDate
    """

    def format_date(value):
        if isinstance(value, date):
            return value.isoformat()
        return str(value)

    state = state.upper().strip()
    title_contains = title_contains.upper().strip()
    begin_date = format_date(incident_begin_date)
    end_date = format_date(incident_end_date)

    # FEMA's API uses OData filter syntax.
    odata_filter = (
        f"state eq '{state}' "
        f"and declarationType eq 'DR' "
        f"and substringof('{title_contains}',declarationTitle) "
        f"and incidentBeginDate ge {begin_date} "
        f"and incidentEndDate le {end_date}"
    )

    params = {
        "$filter": odata_filter,
        "$select": (
            "disasterNumber,declarationTitle,"
            "incidentBeginDate,incidentEndDate"
        ),
        "$orderby": "incidentBeginDate asc",
        "$top": 1000,
    }

    payload, source_url = _request_fema(
        params=params,
        timeout=timeout,
    )

    records = payload.get(
        "DisasterDeclarationsSummaries",
        [],
    )

    columns = [
        "disasterNumber",
        "declarationTitle",
        "incidentBeginDate",
        "incidentEndDate",
    ]

    results = (
        pd.DataFrame(records, columns=columns)
        .drop_duplicates(subset="disasterNumber")
        .reset_index(drop=True)
    )

    return results, source_url


def get_disaster_areas(
    disaster_number: int | str,
    state: str | None = None,
    timeout: int = 30,
) -> tuple[pd.DataFrame, str]:
    """
    Return FEMA designated areas for one disaster declaration.

    Parameters
    ----------
    disaster_number : int or str
        FEMA disaster number, such as 1234.
    timeout : int
        HTTP request timeout in seconds.

    Returns
    -------
    pandas.DataFrame
        One row per FEMA designated area.
    """

    disaster_number = int(disaster_number)

    filters = [f"disasterNumber eq {disaster_number}"]
    if state:
        state = state.strip().upper()
        if len(state) != 2 or not state.isalpha():
            raise ValueError("state must be a two-letter abbreviation, such as SD")
        filters.append(f"state eq '{state}'")

    params = {
        "$filter": " and ".join(filters),
        "$select": (
            "disasterNumber,state,designatedArea,"
            "fipsStateCode,fipsCountyCode,placeCode,"
            "declarationType"
        ),
        "$orderby": "state asc,designatedArea asc",
        "$top": 1000,
    }

    payload, source_url = _request_fema(
        params=params,
        timeout=timeout,
    )

    records = payload.get(
        "DisasterDeclarationsSummaries",
        [],
    )

    columns = [
        "disasterNumber",
        "state",
        "designatedArea",
        "fipsStateCode",
        "fipsCountyCode",
        "placeCode"
    ]

    areas = pd.DataFrame(records, columns=columns)

    return (
        areas.drop_duplicates().reset_index(drop=True),
        source_url,
    )


def padded_fips(series, width: int) -> pd.Series:
    return (
        pd.to_numeric(series, errors="coerce")
        .astype("Int64")
        .astype("string")
        .str.zfill(width)
    )


def make_county_fips(areas: pd.DataFrame) -> list[str]:
    state_fips = padded_fips(
        areas["fipsStateCode"],
        2,
    )

    county_fips = padded_fips(
        areas["fipsCountyCode"],
        3,
    )

    result = (
        state_fips
        + county_fips
    )

    return (
        result
        .dropna()
        .drop_duplicates()
        .tolist()
    )


def search_fema_disasters(
    state: str,
    title_contains: str,
    incident_begin_date: str,
    incident_end_date: str,
) -> dict[str, Any]:
    """
    Search FEMA major disaster declarations for candidate declarations for 
    a specific state.

    The state is required because hurricanes and other large incidents
    may result in separate FEMA declarations for multiple states.

    If the user names a hurricane but does not identify a state, ask
    which state or states should be searched. Do not guess a state. 
    You can use the search_fema_disasters_by_states to get disaster
    numbers for multiple explicit states.

    Required search criteria:
    - state: Two-letter state abbreviation, such as SD.
    - title_contains: Important text from the FEMA declaration title,
      such as STORM, FLOOD, or TORNADO. For named storms, like HURRICANE,
      this can include the name, such as HURRICANE HELENE.
    - incident_begin_date: Earliest incident date, formatted YYYY-MM-DD.
    - incident_end_date: Latest incident date, formatted YYYY-MM-DD.

    The title text and both date bounds are required because broad FEMA
    searches can return too many records. The calling agent should ask
    the user for missing information before calling this tool.

    If there are no results returned, attempt to pad the incident
    end dates by one month because they can be much later than the
    period of the incident. For example, hurricane Helene did not continue
    being a hurricane through December of 2024, but the disaster incident
    end date is in December of 2024. Only try this once - and if nothing is
    returned after that, tell the user. Do not continue to try to find a 
    matching disaster.

    Use a reasonably specific title term and a narrow date range. For
    example, a request for a storm in South Dakota during June or July of 2026
    should use:
        state="SD"
        title_contains="STORM"
        incident_begin_date="2026-06-01"
        incident_end_date="2026-07-31"

    This tool returns candidate declarations. If multiple declarations
    are returned, do not choose one automatically. Always ask the user to
    select or confirm a disaster number before calling
    get_fema_designated_areas.

    IMPORTANT SOURCE-DISCLOSURE REQUIREMENT:
    When presenting results from this tool, include the complete value
    of source.api_url or source.attribution_text. Do not cite only
    the FEMA homepage or the API base URL. Do not overload the user with
    multiple urls that are nearly identical.
    """

    state = state.strip().upper()
    title_contains = title_contains.strip().upper()

    if len(state) != 2 or not state.isalpha():
        raise ValueError(
            "state must be a two-letter abbreviation, such as SD"
        )

    if not title_contains:
        raise ValueError(
            "title_contains is required; use a term such as STORM or FLOOD"
        )

    try:
        begin = date.fromisoformat(incident_begin_date)
        end = date.fromisoformat(incident_end_date)
    except ValueError as exc:
        raise ValueError(
            "Dates must use YYYY-MM-DD format"
        ) from exc

    if begin > end:
        raise ValueError(
            "incident_begin_date must be on or before incident_end_date"
        )

    # Optional safety limit to prevent excessively broad searches.
    if (end - begin).days > 366:
        raise ValueError(
            "Please provide a date range of one year or less"
        )

    results, source_url = get_fema_disasters(
        state=state,
        title_contains=title_contains,
        incident_begin_date=begin.isoformat(),
        incident_end_date=end.isoformat(),
    )

    records = (
        results.where(pd.notna(results), None)
        .to_dict(orient="records")
    )

    return {
        "search_criteria": {
            "state": state,
            "title_contains": title_contains,
            "incident_begin_date": begin.isoformat(),
            "incident_end_date": end.isoformat(),
        },
        "count": len(records),
        "disasters": records,
        "source": {
            "provider": "Federal Emergency Management Agency",
            "dataset": "DisasterDeclarationsSummaries",
            "api_url": source_url,
            "attribution_text": (
                "Source: FEMA DisasterDeclarationsSummaries API. "
                f"API URL: {source_url}"
            ),
        },
        "next_step": (
            "Select or confirm a disaster_number before retrieving "
            "designated areas."
            if len(records) != 1
            else "A single candidate was found; confirm it before proceeding."
        ),
    }

def get_fema_designated_areas(
    disaster_number: int,
    state: str | None = None,
) -> dict[str, Any]:
    """
    Get FEMA-designated areas for a disaster declaration.

    IMPORTANT SOURCE-DISCLOSURE REQUIREMENT:
    When presenting results from this tool, include the complete value
    of source.api_url or source.attribution_text. Do not cite only
    the FEMA homepage or the API base URL. Do not overload the user with
    multiple urls that are nearly identical.

    Args:
        disaster_number: FEMA disaster number, for example 1234.
        state: Optional two-letter state abbreviation, for example SD.

    Returns:
        A JSON-serializable object containing designated areas and
        normalized county FIPS codes.
    """

    if disaster_number <= 0:
        raise ValueError("disaster_number must be a positive integer")

    areas, source_url = get_disaster_areas(
        disaster_number=disaster_number,
        state=state,
    )

    # Normalize FIPS values before returning them.
    areas["fipsStateCode"] = (
        areas["fipsStateCode"]
        .astype("string")
        .str.extract(r"(\d+)", expand=False)
        .str.zfill(2)
    )

    areas["fipsCountyCode"] = (
        areas["fipsCountyCode"]
        .astype("string")
        .str.extract(r"(\d+)", expand=False)
        .str.zfill(3)
    )

    areas["countyFips"] = (
        areas["fipsStateCode"]
        + areas["fipsCountyCode"]
    )

    # Convert the DataFrame to ordinary Python dictionaries.
    records = areas.where(pd.notna(areas), None).to_dict(
        orient="records"
    )

    return {
        "disaster_number": disaster_number,
        "state": state.upper() if state else None,
        "count": len(records),
        "areas": records,
        "source": {
            "provider": "Federal Emergency Management Agency",
            "dataset": "DisasterDeclarationsSummaries",
            "api_url": source_url,
            "attribution_text": (
                "Source: FEMA DisasterDeclarationsSummaries API. "
                f"API URL: {source_url}"
            ),
        },
    }

def register_tools(mcp: FastMCP) -> None:
    mcp.tool()(search_fema_disasters)
    mcp.tool()(get_fema_designated_areas)
