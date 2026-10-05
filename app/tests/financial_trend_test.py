"""
Live test of the multi-year cost-report path against CMS.
No LLM required. Run with: python -m app.tests.financial_trend_test
"""

from pprint import pprint

from app.services.cost_report_service import (
    get_cost_report_datasets,
    get_financial_data_by_hospital,
    get_financial_history_by_hospital,
)
from app.tools.trend_tools import analyze_financial_trend_for_hospital


FACILITY_ID = "510002"  # Greenbrier Valley Medical Center, WV


def test_dataset_discovery():
    print("\n=== Test 1: Dataset discovery from CMS catalog ===")

    datasets = get_cost_report_datasets()
    years = sorted(datasets)

    print(f"{len(years)} dataset years: {years[0]}-{years[-1]}")

    assert len(years) >= 10
    assert years[-1] >= 2023

    print("PASS")


def test_latest_record():
    print("\n=== Test 2: Latest available record ===")

    record = get_financial_data_by_hospital(FACILITY_ID)

    assert record is not None
    print(
        f"report_year={record.report_year} "
        f"FY {record.fiscal_year_begin}..{record.fiscal_year_end} "
        f"rural={record.rural_versus_urban} "
        f"NPR={record.net_patient_revenue}"
    )

    assert record.report_year == max(get_cost_report_datasets())

    print("PASS")


def test_history_and_trend():
    print("\n=== Test 3: Five-year history and trend ===")

    history = get_financial_history_by_hospital(FACILITY_ID)

    print("years requested:", history.years_requested)
    print("years with data:", history.years_with_data)
    print("years without report:", history.years_without_report)
    print("years unavailable:", history.years_unavailable)

    # CMS occasionally rotates dataset IDs mid-day; tolerate a gap
    # but require that the multi-year path mostly works.
    assert len(history.records) >= 3

    trend = analyze_financial_trend_for_hospital(FACILITY_ID)

    print("\nPer-year indicators:")
    for item in trend.yearly_indicators:
        print(
            f"  {item.report_year}: margin={item.operating_margin} "
            f"occupancy={item.occupancy_rate} "
            f"liab/asset={item.liability_to_asset_ratio} "
            f"ctc={item.cost_to_charge_ratio}"
        )

    print("\nIndicator trends:")
    for name, summary in trend.indicator_trends.items():
        print(
            f"  {name}: {summary.first_year}={summary.first_value} -> "
            f"{summary.last_year}={summary.last_value} "
            f"change={summary.change} ({summary.direction})"
        )

    print("\nDistress signals:")
    pprint(
        {
            "negative_margin_years":
                trend.years_with_negative_operating_margin,
            "consecutive_negative":
                trend.consecutive_negative_operating_margin_years,
            "liabilities_exceed_assets":
                trend.years_with_liabilities_exceeding_assets,
            "average_margin": trend.average_operating_margin,
        }
    )

    assert trend.is_rural is True
    assert trend.years_with_data == history.years_with_data

    print("PASS")


def test_explicit_range():
    print("\n=== Test 4: Explicit range 2011-2014 ===")

    history = get_financial_history_by_hospital(
        FACILITY_ID,
        start_year=2011,
        end_year=2014,
    )

    print("years with data:", history.years_with_data)
    print("years unavailable:", history.years_unavailable)

    assert history.years_requested == [2011, 2012, 2013, 2014]
    assert len(history.records) >= 3

    print("PASS")


def run_tests():
    print("\n========================================")
    print("Financial Trend Service Tests")
    print("========================================")

    test_dataset_discovery()
    test_latest_record()
    test_history_and_trend()
    test_explicit_range()

    print("\n========================================")
    print("ALL FINANCIAL TREND TESTS PASSED")
    print("========================================\n")


if __name__ == "__main__":
    run_tests()
