"""Typed financial records, computed indicators and multi-year evidence summaries."""

from pydantic import BaseModel


class HospitalFinancialRecord(BaseModel):
    """Parsed financial source fields for one selected CMS report."""

    facility_id: str
    hospital_name: str
    fiscal_year_begin: str
    fiscal_year_end: str

    # Year of the CMS cost-report dataset the record came from.
    # CMS publishes one dataset per year; a hospital's fiscal year
    # inside that dataset may not match the calendar year.
    report_year: int | None = None

    rural_versus_urban: str | None = None
    number_of_beds: float | None = None
    total_days: float | None = None
    total_bed_days_available: float | None = None
    total_discharges: float | None = None

    net_patient_revenue: float | None = None
    total_operating_expense: float | None = None
    net_income_from_service: float | None = None
    net_income: float | None = None

    total_assets: float | None = None
    total_liabilities: float | None = None

    total_costs: float | None = None
    cost_to_charge_ratio: float | None = None
    uncompensated_care: float | None = None


class FinancialIndicators(BaseModel):
    """Calculated metrics and explicit missing input fields for one report."""

    facility_id: str
    hospital_name: str

    report_year: int | None = None
    fiscal_year_begin: str | None = None
    fiscal_year_end: str | None = None

    # "R" (rural) or "U" (urban) as reported in the CMS cost report.
    rural_versus_urban: str | None = None
    # Convenience flag derived from rural_versus_urban.
    # None when the cost report does not classify the hospital.
    is_rural: bool | None = None

    occupancy_rate: float | None = None
    operating_margin: float | None = None
    liability_to_asset_ratio: float | None = None
    cost_to_charge_ratio: float | None = None

    missing_fields: list[str] = []
    # Values remain traceable; these metrics must not be ranked or interpreted.
    blocked_metrics: list[str] = []
    quality_warnings: list[dict] = []


class FinancialHistory(BaseModel):
    """Reports with missing filings separated from unavailable datasets."""

    facility_id: str
    years_requested: list[int]
    years_with_data: list[int]
    # Dataset was reachable but no matching hospital report was found.
    years_without_report: list[int]
    # Dataset could not be retrieved; value is the reason.
    years_unavailable: dict[int, str]
    records: list[HospitalFinancialRecord]


class IndicatorTrend(BaseModel):
    """Observed endpoints and deterministic direction for one indicator."""

    indicator: str
    values_by_year: dict[int, float | None]
    years_available: int

    first_year: int | None = None
    first_value: float | None = None
    last_year: int | None = None
    last_value: float | None = None

    # last_value - first_value, in the indicator's own units.
    change: float | None = None

    # improving | worsening | stable | increased | decreased
    # | insufficient_data
    direction: str
    quality_warnings: list[dict] = []


class FinancialTrend(BaseModel):
    """Combined yearly indicators, trend summaries and reported distress signals."""

    facility_id: str
    hospital_name: str | None = None

    rural_versus_urban: str | None = None
    is_rural: bool | None = None

    years_requested: list[int]
    years_with_data: list[int]
    years_without_report: list[int]
    years_unavailable: dict[int, str]

    yearly_indicators: list[FinancialIndicators]
    indicator_trends: dict[str, IndicatorTrend]

    years_with_negative_operating_margin: list[int]
    consecutive_negative_operating_margin_years: int
    years_with_liabilities_exceeding_assets: list[int]
    average_operating_margin: float | None = None
    quality_warnings: list[dict] = []
