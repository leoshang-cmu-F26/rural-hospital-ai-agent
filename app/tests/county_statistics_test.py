"""Offline uncertainty, workforce denominator and county coverage contracts."""

from unittest.mock import Mock

import pytest

from app.services import county_statistics_import as statistics
from app.services import reference_import_service as importer


@pytest.mark.parametrize(
    "raw", [None, "", ".", "-999999999", "-666666666", "nan", "inf"]
)
def test_missing_values_are_not_zero(raw):
    assert statistics.numeric_value(raw) is None
    assert statistics.numeric_value("0") == 0


def test_controlled_moe_is_not_zero():
    measure = statistics.acs_measure(
        {"DP05_0001E": "100", "DP05_0001M": "-555555555"},
        "DP05_0001E",
        "people",
        "Total population",
    )
    assert measure["estimate"] == 100
    assert measure["moe"] is None
    assert measure["moe_status"] == "controlled_estimate_moe_not_applicable"
    assert measure["confidence_level"] == 0.9


def test_percent_moe_uses_pm_and_preserves_units():
    measure = statistics.acs_measure(
        {"DP03_0099PE": "8.1", "DP03_0099PM": "1.2"},
        "DP03_0099PE",
        "percent",
        "Civilian noninstitutionalized population",
    )
    assert measure["moe"] == 1.2
    assert measure["moe_variable"] == "DP03_0099PM"


def test_workforce_ratio_uses_same_year_population():
    measure = statistics.workforce_measure(
        {"np_npi_24": "10", "popn_est_24": "20000", "popn_est_23": "10000"},
        "np_npi_24",
        2024,
        "NPI count",
        "CMS NPI",
    )
    assert measure["per_100000_residents"] == 50
    assert measure["residents_per_provider"] == 2000
    assert measure["population_year"] == measure["count_year"] == 2024


def test_zero_workforce_and_missing_population():
    zero = statistics.workforce_measure(
        {"n": "0", "popn_est_24": "100"}, "n", 2024, "", ""
    )
    assert zero["per_100000_residents"] == 0
    assert zero["residents_per_provider"] is None
    missing = statistics.workforce_measure(
        {"n": "-999999999", "popn_est_24": "100"}, "n", 2024, "", ""
    )
    assert missing["count"] is None
    assert missing["per_100000_residents"] is None


def test_join_uses_fips_and_rejects_missing_counties(monkeypatch):
    monkeypatch.setattr(
        statistics,
        "fetch_acs_counties",
        lambda state: {"juneau": {"state_fips": "55", "county_fips": "057"}},
    )
    monkeypatch.setattr(
        statistics,
        "fetch_workforce_counties",
        lambda state: {"55057": {"measures": {}}},
    )
    assert "health_workforce" in statistics.fetch_county_statistics("WI")["juneau"]
    monkeypatch.setattr(statistics, "fetch_workforce_counties", lambda state: {})
    with pytest.raises(ValueError, match="missing"):
        statistics.fetch_county_statistics("WI")


def test_reference_refresh_keeps_extended_statistics(monkeypatch):
    fetch = Mock(return_value={"test": {"acs_measures": {}, "health_workforce": {}}})
    monkeypatch.setattr(statistics, "fetch_county_statistics", fetch)
    assert "health_workforce" in importer.fetch_demographics("CA")["test"]
    fetch.assert_called_once_with("CA")


def test_county_tool_reads_snapshots(monkeypatch):
    from app.services import census_service
    from app.tools.agent_tools import get_county_health_context

    monkeypatch.setattr(
        census_service,
        "get_county_demographics",
        lambda fips, county: {
            "state_fips": fips,
            "county": county,
            "acs_measures": {"test": {}},
        },
    )
    result = get_county_health_context.invoke(
        {"state": "California", "county": "Alpine"}
    )
    assert result["state_fips"] == "06"
    assert "acs_measures" in result
