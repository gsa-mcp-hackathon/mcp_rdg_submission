"""Shared obligation table settings and allowed tool parameter values."""

from __future__ import annotations

from typing import Literal


TABLE = "rd_edapt.analytics_bronze.pfd_obligations"
MAX_LIMIT = 200
ROW_ID_EXPR = "substr(sha2(to_json(struct(*)), 256), 1, 16)"
CategoryColumn = Literal[
    "obl_fscl_yr",
    "obligation_state_abr",
    "state_name",
    "obligation_county_name",
    "obligation_county_fips",
    "programarea",
    "programlabel",
    "fundingcode",
    "investment_type",
    "portfolio_group",
    "congr_dist_cd",
    "persistent_poverty_indicator",
    "naics_industry_sector",
    "naics_industry_subsector",
    "lender_name",
]
SortOrder = Literal[
    "obl_amt_desc", "obl_amt_asc", "fiscal_year_desc", "fiscal_year_asc"
]
_ORDER_SQL = {
    "obl_amt_desc": "obl_amt DESC",
    "obl_amt_asc": "obl_amt ASC",
    "fiscal_year_desc": "obl_fscl_yr DESC, obl_amt DESC",
    "fiscal_year_asc": "obl_fscl_yr ASC, obl_amt DESC",
}
