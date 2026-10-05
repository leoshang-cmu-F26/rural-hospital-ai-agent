"""
Deterministic multi-year trend analysis over FinancialIndicators.

Everything in the "pure" region works on in-memory objects and is
covered by unit tests. analyze_financial_trend_for_hospital() at the
bottom orchestrates the CMS retrieval and is shared by the API route
and the agent tool.
"""

from statistics import mean

from app.models.financial import (
    FinancialIndicators,
    FinancialTrend,
    IndicatorTrend,
)
from app.services.cost_report_service import (
    get_financial_history_by_hospital,
)
from app.tools.financial_tools import calculate_financial_indicators


TREND_INDICATORS = (
    "operating_margin",
    "occupancy_rate",
    "liability_to_asset_ratio",
    "cost_to_charge_ratio",
)

HIGHER_IS_BETTER = {"operating_margin", "occupancy_rate"}
LOWER_IS_BETTER = {"liability_to_asset_ratio"}

# Absolute change below which an indicator is reported as "stable".
# Percent-based indicators use 1 percentage point; the cost-to-charge
# ratio is a plain ratio so it uses 0.01.
STABLE_THRESHOLDS = {
    "operating_margin": 1.0,
    "occupancy_rate": 1.0,
    "liability_to_asset_ratio": 1.0,
    "cost_to_charge_ratio": 0.01,
}


# region Pure trend math

def classify_direction(indicator: str, change: float | None) -> str:
    if change is None:
        return "insufficient_data"

    if abs(change) < STABLE_THRESHOLDS.get(indicator, 0.0):
        return "stable"

    if indicator in HIGHER_IS_BETTER:
        return "improving" if change > 0 else "worsening"

    if indicator in LOWER_IS_BETTER:
        return "improving" if change < 0 else "worsening"

    return "increased" if change > 0 else "decreased"


def count_trailing_true(flags: list[bool]) -> int:
    count = 0

    for flag in reversed(flags):
        if not flag:
            break
        count += 1

    return count


def summarize_indicator_trend(
    indicator: str,
    yearly_indicators: list[FinancialIndicators],
) -> IndicatorTrend:
    ordered = sorted(
        yearly_indicators,
        key=lambda item: item.report_year or 0,
    )

    values_by_year = {
        item.report_year: getattr(item, indicator)
        for item in ordered
        if item.report_year is not None
    }

    available = [
        (year, value)
        for year, value in values_by_year.items()
        if value is not None
    ]

    if len(available) < 2:
        first_year, first_value = available[0] if available else (None, None)
        return IndicatorTrend(
            indicator=indicator,
            values_by_year=values_by_year,
            years_available=len(available),
            first_year=first_year,
            first_value=first_value,
            last_year=first_year,
            last_value=first_value,
            change=None,
            direction="insufficient_data",
        )

    first_year, first_value = available[0]
    last_year, last_value = available[-1]
    change = round(last_value - first_value, 4)

    return IndicatorTrend(
        indicator=indicator,
        values_by_year=values_by_year,
        years_available=len(available),
        first_year=first_year,
        first_value=first_value,
        last_year=last_year,
        last_value=last_value,
        change=change,
        direction=classify_direction(indicator, change),
    )


def build_financial_trend(
    facility_id: str,
    yearly_indicators: list[FinancialIndicators],
    years_requested: list[int],
    years_without_report: list[int],
    years_unavailable: dict[int, str],
) -> FinancialTrend:
    ordered = sorted(
        yearly_indicators,
        key=lambda item: item.report_year or 0,
    )

    latest = ordered[-1] if ordered else None

    rural_source = next(
        (item for item in reversed(ordered) if item.is_rural is not None),
        None,
    )

    negative_margin_flags = [
        item.operating_margin is not None and item.operating_margin < 0
        for item in ordered
    ]

    margins = [
        item.operating_margin
        for item in ordered
        if item.operating_margin is not None
    ]

    return FinancialTrend(
        facility_id=facility_id,
        hospital_name=latest.hospital_name if latest else None,

        rural_versus_urban=(
            rural_source.rural_versus_urban if rural_source else None
        ),
        is_rural=rural_source.is_rural if rural_source else None,

        years_requested=years_requested,
        years_with_data=[
            item.report_year
            for item in ordered
            if item.report_year is not None
        ],
        years_without_report=sorted(years_without_report),
        years_unavailable=dict(sorted(years_unavailable.items())),

        yearly_indicators=ordered,
        indicator_trends={
            indicator: summarize_indicator_trend(indicator, ordered)
            for indicator in TREND_INDICATORS
        },

        years_with_negative_operating_margin=[
            item.report_year
            for item, is_negative in zip(ordered, negative_margin_flags)
            if is_negative and item.report_year is not None
        ],
        consecutive_negative_operating_margin_years=
            count_trailing_true(negative_margin_flags),
        years_with_liabilities_exceeding_assets=[
            item.report_year
            for item in ordered
            if item.liability_to_asset_ratio is not None
            and item.liability_to_asset_ratio > 100
            and item.report_year is not None
        ],
        average_operating_margin=(
            round(mean(margins), 2) if margins else None
        ),
    )

# endregion


# region Orchestration

def analyze_financial_trend_for_hospital(
    facility_id: str,
    start_year: int | None = None,
    end_year: int | None = None,
) -> FinancialTrend:
    """
    Retrieve multi-year CMS cost-report data for a hospital and
    build its FinancialTrend. May raise ValueError (bad year range)
    or CostReportUnavailableError (no dataset reachable at all).
    """
    history = get_financial_history_by_hospital(
        facility_id=facility_id,
        start_year=start_year,
        end_year=end_year,
    )

    yearly_indicators = [
        calculate_financial_indicators(record)
        for record in history.records
    ]

    return build_financial_trend(
        facility_id=history.facility_id,
        yearly_indicators=yearly_indicators,
        years_requested=history.years_requested,
        years_without_report=history.years_without_report,
        years_unavailable=history.years_unavailable,
    )

# endregion
