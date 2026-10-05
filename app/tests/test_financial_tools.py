"""
Offline unit tests for the deterministic indicator and trend math.
Run with: pytest
"""

from app.models.financial import (
    FinancialIndicators,
    HospitalFinancialRecord,
)
from app.tools.financial_tools import (
    calculate_financial_indicators,
    is_rural_hospital,
)
from app.tools.trend_tools import (
    build_financial_trend,
    classify_direction,
    count_trailing_true,
    summarize_indicator_trend,
)


def make_record(**overrides) -> HospitalFinancialRecord:
    base = dict(
        facility_id="510002",
        hospital_name="TEST HOSPITAL",
        fiscal_year_begin="2023-01-01",
        fiscal_year_end="2023-12-31",
        report_year=2023,
    )
    base.update(overrides)
    return HospitalFinancialRecord(**base)


def make_indicators(
    year: int,
    margin: float | None = None,
    liability: float | None = None,
    occupancy: float | None = None,
    cost_to_charge: float | None = None,
    is_rural: bool | None = True,
) -> FinancialIndicators:
    return FinancialIndicators(
        facility_id="510002",
        hospital_name="TEST HOSPITAL",
        report_year=year,
        rural_versus_urban="R" if is_rural else None,
        is_rural=is_rural,
        operating_margin=margin,
        liability_to_asset_ratio=liability,
        occupancy_rate=occupancy,
        cost_to_charge_ratio=cost_to_charge,
    )


# region Indicators

def test_indicators_on_complete_record():
    record = make_record(
        rural_versus_urban="R",
        total_days=10353,
        total_bed_days_available=24090,
        net_income_from_service=-16703332,
        net_patient_revenue=87003190,
        total_liabilities=143739703,
        total_assets=127983969,
        cost_to_charge_ratio=0.264803,
    )

    indicators = calculate_financial_indicators(record)

    assert indicators.occupancy_rate == 42.98
    assert indicators.operating_margin == -19.2
    assert indicators.liability_to_asset_ratio == 112.31
    assert indicators.cost_to_charge_ratio == 0.264803
    assert indicators.missing_fields == []
    assert indicators.is_rural is True
    assert indicators.rural_versus_urban == "R"
    assert indicators.report_year == 2023
    assert indicators.fiscal_year_begin == "2023-01-01"


def test_indicators_report_missing_fields_and_guard_zero_denominators():
    record = make_record(
        total_days=100,
        total_bed_days_available=0,
        net_income_from_service=5,
        net_patient_revenue=0,
        total_liabilities=None,
        total_assets=0,
    )

    indicators = calculate_financial_indicators(record)

    assert indicators.occupancy_rate is None
    assert indicators.operating_margin is None
    assert indicators.liability_to_asset_ratio is None
    assert indicators.cost_to_charge_ratio is None
    # Zero denominators are present, not missing; None fields are.
    assert indicators.missing_fields == [
        "total_liabilities",
        "cost_to_charge_ratio",
    ]
    assert indicators.is_rural is None


def test_is_rural_mapping():
    assert is_rural_hospital(make_record(rural_versus_urban="R")) is True
    assert is_rural_hospital(make_record(rural_versus_urban=" r ")) is True
    assert is_rural_hospital(make_record(rural_versus_urban="U")) is False
    assert is_rural_hospital(make_record(rural_versus_urban=None)) is None
    assert is_rural_hospital(make_record(rural_versus_urban="?")) is None

# endregion


# region Trend math

def test_classify_direction():
    assert classify_direction("operating_margin", 5.0) == "improving"
    assert classify_direction("operating_margin", -5.0) == "worsening"
    assert classify_direction("operating_margin", 0.4) == "stable"
    assert classify_direction("liability_to_asset_ratio", -5.0) == "improving"
    assert classify_direction("liability_to_asset_ratio", 5.0) == "worsening"
    assert classify_direction("cost_to_charge_ratio", 0.05) == "increased"
    assert classify_direction("cost_to_charge_ratio", -0.05) == "decreased"
    assert classify_direction("cost_to_charge_ratio", 0.005) == "stable"
    assert classify_direction("operating_margin", None) == "insufficient_data"


def test_count_trailing_true():
    assert count_trailing_true([True, False, True, True]) == 2
    assert count_trailing_true([True, True, True]) == 3
    assert count_trailing_true([True, False]) == 0
    assert count_trailing_true([]) == 0


def test_trend_directions_and_distress_signals():
    yearly = [
        make_indicators(2020, margin=-2.0, liability=90.0, occupancy=50.0, cost_to_charge=0.30),
        make_indicators(2021, margin=-5.0, liability=101.0, occupancy=50.5, cost_to_charge=0.28),
        make_indicators(2022, margin=-8.0, liability=110.0, occupancy=49.8, cost_to_charge=0.26),
    ]

    trend = build_financial_trend(
        facility_id="510002",
        yearly_indicators=yearly,
        years_requested=[2020, 2021, 2022],
        years_without_report=[],
        years_unavailable={},
    )

    margin = trend.indicator_trends["operating_margin"]
    assert margin.first_year == 2020
    assert margin.last_year == 2022
    assert margin.change == -6.0
    assert margin.direction == "worsening"
    assert margin.years_available == 3

    assert trend.indicator_trends["liability_to_asset_ratio"].direction == "worsening"
    assert trend.indicator_trends["occupancy_rate"].direction == "stable"
    assert trend.indicator_trends["cost_to_charge_ratio"].direction == "decreased"

    assert trend.years_with_data == [2020, 2021, 2022]
    assert trend.years_with_negative_operating_margin == [2020, 2021, 2022]
    assert trend.consecutive_negative_operating_margin_years == 3
    assert trend.years_with_liabilities_exceeding_assets == [2021, 2022]
    assert trend.average_operating_margin == -5.0
    assert trend.is_rural is True
    assert trend.hospital_name == "TEST HOSPITAL"


def test_trend_handles_gaps_and_missing_values():
    yearly = [
        make_indicators(2022, margin=1.0, liability=80.0),
        make_indicators(2019, margin=3.0, liability=70.0),
        make_indicators(2021, margin=None, liability=75.0),
    ]

    trend = build_financial_trend(
        facility_id="510002",
        yearly_indicators=yearly,
        years_requested=[2019, 2020, 2021, 2022, 2023],
        years_without_report=[2020],
        years_unavailable={2023: "dataset ID no longer exists at CMS"},
    )

    # Input order does not matter; output is sorted by year.
    assert trend.years_with_data == [2019, 2021, 2022]
    assert trend.years_without_report == [2020]
    assert trend.years_unavailable == {2023: "dataset ID no longer exists at CMS"}

    margin = trend.indicator_trends["operating_margin"]
    assert margin.years_available == 2
    assert margin.first_year == 2019
    assert margin.last_year == 2022
    assert margin.change == -2.0
    assert margin.direction == "worsening"
    assert margin.values_by_year == {2019: 3.0, 2021: None, 2022: 1.0}

    assert trend.years_with_negative_operating_margin == []
    assert trend.consecutive_negative_operating_margin_years == 0
    assert trend.average_operating_margin == 2.0


def test_trend_with_single_year_is_insufficient():
    yearly = [make_indicators(2024, margin=-3.0)]

    summary = summarize_indicator_trend("operating_margin", yearly)

    assert summary.direction == "insufficient_data"
    assert summary.change is None
    assert summary.first_year == 2024
    assert summary.first_value == -3.0
    assert summary.years_available == 1


def test_trend_with_no_data():
    trend = build_financial_trend(
        facility_id="000000",
        yearly_indicators=[],
        years_requested=[2020, 2021],
        years_without_report=[2020, 2021],
        years_unavailable={},
    )

    assert trend.hospital_name is None
    assert trend.is_rural is None
    assert trend.years_with_data == []
    assert trend.consecutive_negative_operating_margin_years == 0
    assert trend.average_operating_margin is None
    assert trend.indicator_trends["operating_margin"].direction == "insufficient_data"

# endregion
