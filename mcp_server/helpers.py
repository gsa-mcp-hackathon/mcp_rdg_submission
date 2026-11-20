"""Helper tools"""

from datetime import date, datetime
from zoneinfo import ZoneInfo
from mcp.server.fastmcp import FastMCP

async def get_current_date(tz_name: str = "UTC") -> str:
    """Get today's date in the specified Internet Assigned Numbers Authority 
    (IANA) timezone.

    This is helpful if the user asks for relative information, 
    like 'recently' or 'this year' or 'last month'

    Args:
        tz_name: IANA timezone name, such as 'UTC',
                 'America/New_York', or 'Europe/Paris'.

    Returns:
        Today's date in ISO 8601 format: YYYY-MM-DD.
    """
    current_date = datetime.now(ZoneInfo(tz_name)).date()
    return current_date.isoformat()

async def get_current_fiscal_year(tz_name: str = "UTC") -> dict:
    """Get the current U.S. federal fiscal year.

    The federal fiscal year begins October 1 and is named for the year
    in which it ends. For example, October 1, 2025 through September 30,
    2026 is FY 2026.

    Args:
        tz_name: IANA timezone name, such as 'UTC' or
                 'America/New_York'.

    Returns:
        The current fiscal year and its start and end dates.
    """
    current_date = datetime.now(ZoneInfo(tz_name)).date()

    if current_date.month >= 10:
        fiscal_year = current_date.year + 1
        start_year = current_date.year
    else:
        fiscal_year = current_date.year
        start_year = current_date.year - 1

    return {
        "fiscal_year": f"FY {fiscal_year}",
        "fiscal_year_number": fiscal_year,
        "start_date": date(start_year, 10, 1).isoformat(),
        "end_date": date(fiscal_year, 9, 30).isoformat(),
        "as_of_date": current_date.isoformat(),
        "timezone": tz_name,
    }

def register_tools(mcp: FastMCP) -> None:
    mcp.tool()(get_current_date)
    mcp.tool()(get_current_fiscal_year)
