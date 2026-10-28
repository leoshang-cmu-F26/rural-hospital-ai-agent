"""
Deterministic multi-year trend analysis over FinancialIndicators.

Everything in the "pure" region works on in-memory objects and is
covered by unit tests. analyze_financial_trend_for_hospital() at the
bottom orchestrates the CMS retrieval and is shared by the API route
and the agent tool.
"""

from statistics import mean
from datetime import datetime

from app.services.data_quality_service import warning, rural_from_record

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
    """Apply application thresholds; these labels are not official CMS ratings."""
    # Missing endpoints cannot establish a direction.
    if change is None:
        return "insufficient_data"
    if abs(change) < STABLE_THRESHOLDS.get(indicator, 0.0):
        return "stable"

    # Improvement depends on the indicator; cost-to-charge has no quality label.
    if indicator in HIGHER_IS_BETTER:
        if change > 0:
            return "improving"
        return "worsening"
    if indicator in LOWER_IS_BETTER:
        if change < 0:
            return "improving"
        return "worsening"
    if change > 0:
        return "increased"
    return "decreased"


def count_trailing_true(flags: list[bool]) -> int:
    """Count trailing observed flags until the first false value."""
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
    # Order observed reports before comparing endpoints. Missing values stay missing.
    """Describe observed endpoints while flagging reversals and invalid metrics."""
    ordered = sorted(
        yearly_indicators,
        key=lambda item: item.report_year or 0,
    )

    # Build the indicator series from known report years only.
    values_by_year = {}
    for item in ordered:
        if item.report_year is not None:
            values_by_year[item.report_year] = getattr(item, indicator)

    available = []
    for year, value in values_by_year.items():
        if value is not None:
            available.append((year, value))

    # Two observed values are needed to describe a change.
    if len(available) < 2:
        if available:
            first_year, first_value = available[0]
        else:
            first_year = None
            first_value = None
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

    # Compare actual endpoints; do not interpolate missing intervening years.
    first_year, first_value = available[0]
    last_year, last_value = available[-1]
    change = round(last_value - first_value, 4)

    # A net endpoint change must not hide direction reversals or invalid ratios.
    alerts = []
    signs = set()
    for index in range(1, len(available)):
        step = available[index][1] - available[index - 1][1]
        if abs(step) >= STABLE_THRESHOLDS.get(indicator, 0):
            if step > 0:
                signs.add(1)
            elif step < 0:
                signs.add(-1)
    direction = classify_direction(indicator, change)
    if len(signs) > 1:
        direction = 'mixed'
        alerts.append(
            warning(
                'trend_reversals',
                f'{indicator} changes direction within the observed years; an endpoint label would hide the fluctuation.',
                'Describe the observed sequence and endpoint change separately; do not claim sustained improvement or deterioration.',
                metric=indicator,
            )
        )
    for item in ordered:
        if indicator in item.blocked_metrics:
            direction = 'requires_review'
            change = None
            alerts.append(
                warning(
                    'trend_invalid_metric',
                    f'{indicator} contains a year with an invalid denominator or utilization scope.',
                    'Inspect source records; no directional conclusion or endpoint difference is supported.',
                    metric=indicator,
                )
            )
            break
    return IndicatorTrend(
        indicator=indicator,
        quality_warnings=alerts,
        values_by_year=values_by_year,
        years_available=len(available),
        first_year=first_year,
        first_value=first_value,
        last_year=last_year,
        last_value=last_value,
        change=change,
        direction=direction,
    )


def build_financial_trend(
    facility_id: str,
    yearly_indicators: list[FinancialIndicators],
    years_requested: list[int],
    years_without_report: list[int],
    years_unavailable: dict[int, str],
) -> FinancialTrend:
    """Assemble deterministic history summaries without filling missing years."""
    # 1. Order reports and use the latest record for the hospital name.
    ordered = sorted(yearly_indicators, key=lambda item: item.report_year or 0)
    latest = None
    if ordered:
        latest = ordered[-1]
    hospital_name = None
    if latest:
        hospital_name = latest.hospital_name

    # 2. Use the newest reported rural classification; absence remains unknown.
    rural_source = None
    for item in reversed(ordered):
        if item.is_rural is not None:
            rural_source = item
            break
    rural_versus_urban = None
    is_rural = None
    if rural_source:
        rural_versus_urban = rural_source.rural_versus_urban
        is_rural = rural_source.is_rural

    # 3. Collect observed years, operating losses and balance-sheet signals.
    margins = []
    years_with_data = []
    negative_margin_years = []
    liabilities_exceeding_assets_years = []
    for item in ordered:
        is_negative = (
            item.operating_margin is not None
            and item.operating_margin < 0
            and 'operating_margin' not in item.blocked_metrics
        )
        if item.operating_margin is not None and 'operating_margin' not in item.blocked_metrics:
            margins.append(item.operating_margin)
        if item.report_year is not None:
            years_with_data.append(item.report_year)
            if is_negative:
                negative_margin_years.append(item.report_year)
            if (
                'liability_to_asset_ratio' not in item.blocked_metrics
                and item.liability_to_asset_ratio is not None
                and item.liability_to_asset_ratio > 100
            ):
                liabilities_exceeding_assets_years.append(item.report_year)

    # Missing requested years break a consecutive-loss sequence.
    negative_margin_flags = []
    observed_losses = set(negative_margin_years)
    for requested_year in sorted(years_requested):
        negative_margin_flags.append(requested_year in observed_losses)

    # 4. Summarize each metric from actual endpoints and average known margins.
    indicator_trends = {}
    for indicator in TREND_INDICATORS:
        indicator_trends[indicator] = summarize_indicator_trend(indicator, ordered)
    average_margin = None
    if margins:
        average_margin = round(mean(margins), 2)

    # Review dates, gaps and source warnings before describing a multi-year trend.
    quality_warnings = []
    for item in ordered:
        for alert in item.quality_warnings:
            quality_warnings.append(alert)
    for summary in indicator_trends.values():
        for alert in summary.quality_warnings:
            quality_warnings.append(alert)
    if years_without_report or years_unavailable:
        quality_warnings.append(
            warning(
                'trend_year_gaps',
                'Some requested years have no matching report or could not be retrieved.',
                'Describe observed years only; gaps do not establish uninterrupted deterioration or improvement.',
            )
        )
    for index, item in enumerate(ordered):
        if index == 0:
            continue
        previous = ordered[index - 1]
        try:
            begin = datetime.fromisoformat(item.fiscal_year_begin)
            end = datetime.fromisoformat(item.fiscal_year_end)
            prior_begin = datetime.fromisoformat(previous.fiscal_year_begin)
            prior_end = datetime.fromisoformat(previous.fiscal_year_end)
            if begin <= prior_end or abs((end - begin).days - (prior_end - prior_begin).days) > 31:
                raise ValueError('Overlapping or unequal periods')
        except (ValueError, TypeError):
            quality_warnings.append(
                warning(
                    'trend_fiscal_periods',
                    'Trend fiscal periods overlap, differ materially in length, or have missing/invalid dates.',
                    'Review fiscal dates before comparing. Direction labels are withheld pending review.',
                )
            )
            for summary in indicator_trends.values():
                summary.direction = 'requires_review'
                summary.change = None
            break
    _, rural_alerts = rural_from_record(rural_source)
    for alert in rural_alerts:
        quality_warnings.append(alert)

    # 5. Preserve unavailable years in chronological order.
    ordered_unavailable_years = {}
    for year, reason in sorted(years_unavailable.items()):
        ordered_unavailable_years[year] = reason

    # Keep missing filings distinct from retrieval failures.
    return FinancialTrend(
        facility_id=facility_id,
        hospital_name=hospital_name,
        rural_versus_urban=rural_versus_urban,
        is_rural=is_rural,
        years_requested=years_requested,
        years_with_data=years_with_data,
        years_without_report=sorted(years_without_report),
        years_unavailable=ordered_unavailable_years,
        yearly_indicators=ordered,
        indicator_trends=indicator_trends,
        years_with_negative_operating_margin=negative_margin_years,
        consecutive_negative_operating_margin_years=count_trailing_true(negative_margin_flags),
        years_with_liabilities_exceeding_assets=liabilities_exceeding_assets_years,
        average_operating_margin=average_margin,
        quality_warnings=quality_warnings,
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
    # Retrieve source history once, then calculate each yearly record deterministically.
    history = get_financial_history_by_hospital(
        facility_id=facility_id,
        start_year=start_year,
        end_year=end_year,
    )

    yearly_indicators = []
    for record in history.records:
        yearly_indicators.append(calculate_financial_indicators(record))

    return build_financial_trend(
        facility_id=history.facility_id,
        yearly_indicators=yearly_indicators,
        years_requested=history.years_requested,
        years_without_report=history.years_without_report,
        years_unavailable=history.years_unavailable,
    )


# endregion
