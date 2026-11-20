"""
Pydantic models for the FastAPI service.

Source tables (Unity Catalog):
  - rd_edapt.analytics_bronze.pfd_obligations
  - rd_edapt.analytics_bronze.pfd_loans_commercial_guaranteed

Type mapping: STRING -> str, INT/BIGINT -> int, DOUBLE -> Decimal, TIMESTAMP -> datetime.
Every source column is nullable, so every field is Optional.
"""

from __future__ import annotations
from decimal import Decimal
from datetime import datetime
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class TableModel(BaseModel):
    """Shared config: accept rows from dicts/ORM objects and allow field-name or alias input."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# rd_edapt.analytics_bronze.pfd_obligations
# ---------------------------------------------------------------------------
class PfdObligation(TableModel):
    obl_fscl_yr: Optional[int] = None
    obligation_state_abr: Optional[str] = None
    state_name: Optional[str] = None
    obligation_county_name: Optional[str] = None
    obligation_county_fips: Optional[str] = None
    programarea: Optional[str] = None
    programlabel: Optional[str] = None
    fundingcode: Optional[str] = None
    prj_nm: Optional[str] = None
    investment_type: Optional[str] = None
    borr_full_nm_pii_safe: Optional[str] = None
    obligation_city_name: Optional[str] = None
    obligation_zip_cd: Optional[str] = None
    congr_dist_cd: Optional[str] = None
    persistent_poverty_indicator: Optional[int] = None
    lender_name: Optional[str] = None
    naics_industry_sector_cd: Optional[str] = None
    naics_industry_sector: Optional[str] = None
    naics_industry_subsector_cd: Optional[str] = None
    naics_industry_subsector: Optional[str] = None
    naics_cd: Optional[str] = None
    naics_desc: Optional[str] = None
    project_announced_description: Optional[str] = None
    portfolio_group: Optional[str] = None
    obl_amt: Optional[Decimal] = None
    obl_counts: Optional[int] = None


# ---------------------------------------------------------------------------
# rd_edapt.analytics_bronze.pfd_loans_commercial_guaranteed
# ---------------------------------------------------------------------------
class PfdLoanCommercialGuaranteed(TableModel):
    acct_id: Optional[int] = None
    borr_full_nm_pii_safe: Optional[str] = None
    borrower_st_abr: Optional[str] = None
    clse_dt: Optional[str] = None  # stored as STRING in the source table
    clse_fscl_yr: Optional[str] = None  # stored as STRING in the source table
    delinquency_description: Optional[str] = None
    delinquent_age_code: Optional[Decimal] = None
    delinquent_amount: Optional[Decimal] = None
    delinquent_indicator: Optional[int] = None
    guar_pct: Optional[int] = None
    holding_lender_gls_id_key: Optional[int] = None
    holding_lender_id: Optional[int] = None
    holding_lender_name: Optional[str] = None
    holding_lender_onerd_status: Optional[str] = None
    holding_lender_st_abbr: Optional[str] = None
    holding_lender_type: Optional[str] = None
    holding_lender_website: Optional[str] = None
    investment_type: Optional[str] = None
    loan_id: Optional[int] = None
    loan_state_abr: Optional[str] = None
    maturity_date: Optional[datetime] = None
    note_int_rt: Optional[Decimal] = None
    obl_dt: Optional[datetime] = None
    orgn_loan_amt: Optional[Decimal] = None
    portfolio_group: Optional[str] = None
    program_area: Optional[str] = None
    program_label: Optional[str] = None
    project_description: Optional[str] = None
    property_st_abr: Optional[str] = None
    state_name: Optional[str] = None
    unpaid_principal: Optional[Decimal] = None
    unpaid_interest: Optional[Decimal] = None


class PfdLoanCommercialGuaranteedWithLineage(PfdLoanCommercialGuaranteed):
    """Includes the load-metadata columns. Pydantic treats fields that start
    with '_' as private, so these use aliases to map to the real column names."""

    row_hash: Optional[str] = Field(default=None, alias="_row_hash")
    loaded_at: Optional[datetime] = Field(default=None, alias="_loaded_at")
    source_file: Optional[str] = Field(default=None, alias="_source_file")
    run_id: Optional[str] = Field(default=None, alias="_run_id")


# ---------------------------------------------------------------------------
# Generic paginated response wrapper
# ---------------------------------------------------------------------------
T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: List[T]
    total: Optional[int] = None
    limit: int
    offset: int


class PfdObligationPage(Page[PfdObligation]):
    pass


class PfdLoanCommercialGuaranteedPage(Page[PfdLoanCommercialGuaranteed]):
    pass


# make some aggregates for clarity on searching this thing
class PfdOblAggBase(BaseModel):
    fiscal_year: int
    total_obligation_amount: Decimal
    source_row_count: int

# these ones starting with PfdOblAggBase get all of that plus what they include

class PfdStateAggregate(PfdOblAggBase):
    state: str | None

class PfdNaicsAggregate(PfdOblAggBase):
    naics_industry_sector: str | None

class PfdStateNaicsAggregate(PfdOblAggBase):
    state: str | None
    naics_industry_sector: str | None

class PfdProgramAggregate(PfdOblAggBase):
    program_area: str | None

class PfdStateCountyAggregate(PfdOblAggBase):
    state: str | None
    obligation_county_name: str | None
    obligation_county_fips: str | None

class PfdStateAggregatePage(Page[PfdStateAggregate]):
    pass

class PfdProgramAggregatePage(Page[PfdProgramAggregate]):
    pass

class PfdNaicsAggregatePage(Page[PfdNaicsAggregate]):
    pass

class PfdStateNaicsAggregatePage(Page[PfdStateNaicsAggregate]):
    pass

class PfdStateCountyAggregatePage(Page[PfdStateCountyAggregate]):
    pass