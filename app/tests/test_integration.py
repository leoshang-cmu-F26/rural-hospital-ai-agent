"""
Offline integration tests for the alpha system.

These tests run the real FastAPI routes, the LangChain agent tool
wrappers, the CMS cost-report service (catalog lookup, row selection,
parsing, multi-year history) and the deterministic analytics all
wired together. Only the external boundaries are replaced:

- CMS Hospital General Information  -> an in-memory hospital directory
- CMS cost-report HTTP calls         -> a per-(year, CCN) registry
- U.S. Census API                    -> a fake requests.get
- the OpenAI-backed agent run        -> a stub (route tests only)

No network access and no API keys are required. Run with: pytest

The LLM reasoning itself (tool routing, clarification questions,
wording) can only be checked live; see docs/alpha_integration_report.md
for the recorded live scenarios.
"""

from types import SimpleNamespace

import pytest
import requests
from fastapi.testclient import TestClient

import app.api.routes as routes
import app.services.access_service as access_service
import app.services.census_service as census_service
import app.services.cost_report_service as cost_report_service
import app.tools.agent_tools as agent_tools
from app.main import app
from app.models.hospital import Hospital
from app.tools.agent_tools import (
    analyze_financial_trend,
    analyze_healthcare_access,
    analyze_hospital_financials,
    compare_hospitals_by_area,
    get_hospital_demographics,
    search_hospital,
)
from app.utils.state_utils import get_state_fips, normalize_state


# No `with` block: the lifespan hook would start the CMS catalog
# warm-up thread, which needs the network.
client = TestClient(app)


# region Fakes

DATASET_IDS = {year: f"dataset-{year}" for year in range(2020, 2025)}
YEAR_BY_DATASET_ID = {
    dataset_id: year for year, dataset_id in DATASET_IDS.items()
}

HOSPITALS = {
    "510002": Hospital(
        facility_id="510002",
        facility_name="CAMC GREENBRIER VALLEY MEDICAL CENTER, INC",
        address="1320 MAPLEWOOD AVENUE",
        citytown="RONCEVERTE",
        state="WV",
        zip_code="24970",
        countyparish="GREENBRIER",
        hospital_type="Acute Care Hospitals",
    ),
    "510001": Hospital(
        facility_id="510001",
        facility_name="WEST VIRGINIA UNIVERSITY HOSPITALS",
        address="1 MEDICAL CENTER DRIVE",
        citytown="MORGANTOWN",
        state="WV",
        zip_code="26506",
        countyparish="MONONGALIA",
        hospital_type="Acute Care Hospitals",
    ),
    "510024": Hospital(
        facility_id="510024",
        facility_name="MONONGALIA GENERAL HOSPITAL",
        address="1200 J D ANDERSON DRIVE",
        citytown="MORGANTOWN",
        state="WV",
        zip_code="26505",
        countyparish="MONONGALIA",
        hospital_type="Acute Care Hospitals",
    ),
    "194069": Hospital(
        facility_id="194069",
        facility_name="GREENBRIER BEHAVIORAL HEALTH",
        address="201 GREENBRIAR BLVD",
        citytown="COVINGTON",
        state="LA",
        zip_code="70433",
        countyparish="ST. TAMMANY",
        hospital_type="Psychiatric",
    ),
    "650001": Hospital(
        facility_id="650001",
        facility_name="GUAM MEMORIAL HOSPITAL",
        address="850 GOV CARLOS CAMACHO ROAD",
        citytown="TAMUNING",
        state="GU",
        zip_code="96913",
        countyparish="GUAM",
        hospital_type="Acute Care Hospitals",
    ),
}


class FakeResponse:
    def __init__(self, status_code: int = 200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def cms_row(
    ccn: str = "510002",
    name: str = "GREENBRIER VALLEY MEDICAL CENTER",
    begin: str = "2024-01-01",
    end: str = "2024-12-31",
    **overrides,
) -> dict:
    """A raw CMS cost-report row (CMS returns every value as text)."""
    row = {
        "Provider CCN": ccn,
        "Hospital Name": name,
        "Fiscal Year Begin Date": begin,
        "Fiscal Year End Date": end,
        "Rural Versus Urban": "R",
        "Net Patient Revenue": "100000000",
        "Net Income from Service to Patients": "-20000000",
        "Total Assets": "100000000",
        "Total Liabilities": "120000000",
        "Total Days (V + XVIII + XIX + Unknown)": "10000",
        "Total Bed Days Available": "20000",
        "Cost To Charge Ratio": "0.25",
    }
    row.update(overrides)
    return row


def fake_hospital_by_id(facility_id: str):
    return HOSPITALS.get(facility_id.strip())


def fake_search_by_name(name: str):
    return [
        hospital
        for hospital in HOSPITALS.values()
        if name.upper() in hospital.facility_name
    ]


def fake_hospitals_by_state(state: str):
    # The real service returns raw CMS dicts, not Hospital models.
    return [
        hospital.model_dump()
        for hospital in HOSPITALS.values()
        if hospital.state == state.upper()
    ]


@pytest.fixture(autouse=True)
def hospital_directory(monkeypatch):
    """Replace CMS Hospital General Information everywhere it is imported."""
    for module in (routes, agent_tools, access_service, census_service):
        if hasattr(module, "get_hospital_by_id"):
            monkeypatch.setattr(
                module, "get_hospital_by_id", fake_hospital_by_id
            )
        if hasattr(module, "search_hospitals_by_name"):
            monkeypatch.setattr(
                module, "search_hospitals_by_name", fake_search_by_name
            )
        if hasattr(module, "get_hospitals_by_state"):
            monkeypatch.setattr(
                module, "get_hospitals_by_state", fake_hospitals_by_state
            )


@pytest.fixture(autouse=True)
def cost_reports(monkeypatch):
    """
    Replace the two CMS HTTP boundaries of cost_report_service:
    catalog discovery and per-year row requests.

    Tests register an outcome per (year, CCN): a list of rows, an
    HTTP status code, or an exception. Unregistered combinations
    behave like a reachable dataset in which the hospital filed no
    report. Unknown dataset IDs return 404, like a rotated CMS ID.
    """
    registry: dict[tuple[int | None, str], object] = {}

    monkeypatch.setattr(
        cost_report_service,
        "get_cost_report_datasets",
        lambda force_refresh=False: dict(DATASET_IDS),
    )

    def fake_request_rows(dataset_id: str, facility_id: str):
        year = YEAR_BY_DATASET_ID.get(dataset_id)

        if year is None:
            return FakeResponse(status_code=404)

        outcome = registry.get((year, facility_id), [])

        if isinstance(outcome, Exception):
            raise outcome

        if isinstance(outcome, int):
            return FakeResponse(status_code=outcome)

        return FakeResponse(payload=outcome)

    monkeypatch.setattr(cost_report_service, "_request_rows", fake_request_rows)

    cost_report_service._rows_cache.clear()
    cost_report_service._catalog_cache.clear()

    yield registry

    cost_report_service._rows_cache.clear()


CENSUS_ROWS = [
    ["NAME", "DP05_0001E", "DP05_0024E", "DP05_0024PE", "state", "county"],
    ["Greenbrier County, West Virginia", "32000", "8000", "25.0", "54", "025"],
    ["Kanawha County, West Virginia", "180000", "40000", "22.2", "54", "039"],
]


@pytest.fixture
def census(monkeypatch):
    """A Census API that answers with two West Virginia counties."""
    monkeypatch.setattr(census_service, "CENSUS_API_KEY", "offline-test-key")
    monkeypatch.setattr(
        requests, "get", lambda *args, **kwargs: FakeResponse(payload=CENSUS_ROWS)
    )


def register_five_year_history(registry: dict) -> None:
    """2020-2024 for CCN 510002 with no report filed in 2021."""
    registry[(2020, "510002")] = [
        cms_row(
            begin="2020-05-01", end="2021-04-30",
            **{
                "Net Income from Service to Patients": "5000000",
                "Total Liabilities": "80000000",
            },
        )
    ]
    registry[(2022, "510002")] = [
        cms_row(
            begin="2022-05-01", end="2022-12-31",
            **{
                "Net Income from Service to Patients": "2000000",
                "Total Liabilities": "90000000",
            },
        )
    ]
    registry[(2023, "510002")] = [
        cms_row(begin="2023-01-01", end="2023-12-31")
    ]
    registry[(2024, "510002")] = [cms_row()]

# endregion


# region Normal scenarios

def test_health_and_demo_ui_are_served():
    assert client.get("/health").json() == {"status": "healthy"}

    demo = client.get("/demo/")

    assert demo.status_code == 200
    assert "Rural Hospital AI Agent" in demo.text


def test_hospital_lookup_routes():
    search = client.get("/hospitals/search", params={"name": "greenbrier"})
    assert search.status_code == 200
    assert {h["facility_id"] for h in search.json()} == {"510002", "194069"}

    lookup = client.get("/hospitals/510002")
    assert lookup.status_code == 200
    assert lookup.json()["countyparish"] == "GREENBRIER"

    by_state = client.get("/hospitals", params={"state": "west virginia"})
    assert by_state.status_code == 200
    assert by_state.json()["state"] == "WV"
    assert by_state.json()["count"] == 3


def test_indicators_route_computes_from_raw_cms_rows(cost_reports):
    cost_reports[(2024, "510002")] = [cms_row()]

    response = client.get("/hospitals/510002/indicators")

    assert response.status_code == 200
    body = response.json()
    assert body["report_year"] == 2024
    assert body["fiscal_year_end"] == "2024-12-31"
    assert body["is_rural"] is True
    assert body["operating_margin"] == -20.0
    assert body["liability_to_asset_ratio"] == 120.0
    assert body["occupancy_rate"] == 50.0
    assert body["cost_to_charge_ratio"] == 0.25
    assert body["missing_fields"] == []


def test_indicators_route_uses_latest_year_with_a_report(cost_reports):
    # 2024 and 2023 are reachable but empty; the walk-back finds 2022.
    cost_reports[(2022, "510002")] = [
        cms_row(begin="2022-01-01", end="2022-12-31")
    ]

    response = client.get("/hospitals/510002/indicators")

    assert response.status_code == 200
    assert response.json()["report_year"] == 2022


def test_trend_route_end_to_end(cost_reports):
    register_five_year_history(cost_reports)

    response = client.get("/hospitals/510002/trend")

    assert response.status_code == 200
    body = response.json()

    assert body["years_requested"] == [2020, 2021, 2022, 2023, 2024]
    assert body["years_with_data"] == [2020, 2022, 2023, 2024]
    assert body["years_without_report"] == [2021]
    assert body["years_unavailable"] == {}
    assert body["is_rural"] is True

    margin = body["indicator_trends"]["operating_margin"]
    assert (margin["first_year"], margin["first_value"]) == (2020, 5.0)
    assert (margin["last_year"], margin["last_value"]) == (2024, -20.0)
    assert margin["change"] == -25.0
    assert margin["direction"] == "worsening"

    assert body["indicator_trends"]["liability_to_asset_ratio"]["direction"] == "worsening"
    assert body["indicator_trends"]["occupancy_rate"]["direction"] == "stable"
    assert body["indicator_trends"]["cost_to_charge_ratio"]["direction"] == "stable"

    assert body["years_with_negative_operating_margin"] == [2023, 2024]
    assert body["consecutive_negative_operating_margin_years"] == 2
    assert body["years_with_liabilities_exceeding_assets"] == [2023, 2024]
    assert body["average_operating_margin"] == -8.25


def test_agent_financial_tools_return_evidence_for_the_llm(cost_reports):
    register_five_year_history(cost_reports)

    single = analyze_hospital_financials.invoke({"facility_id": "510002"})
    assert single["source"] == "CMS Hospital Provider Cost Report"
    assert single["report_year"] == 2024
    assert single["indicators"]["operating_margin"] == -20.0
    assert single["indicators"]["is_rural"] is True

    trend = analyze_financial_trend.invoke({"facility_id": "510002"})
    assert "multi-year" in trend["source"]
    assert trend["years_with_data"] == [2020, 2022, 2023, 2024]
    assert trend["years_without_report"] == [2021]
    assert trend["distress_signals"]["consecutive_negative_operating_margin_years"] == 2
    assert trend["indicator_trends"]["operating_margin"]["direction"] == "worsening"
    # The ToolMessage is kept compact: one flat row per year.
    assert set(trend["yearly_indicators"][0]) == {
        "report_year", "fiscal_year_begin", "fiscal_year_end",
        "operating_margin", "occupancy_rate",
        "liability_to_asset_ratio", "cost_to_charge_ratio",
        "missing_fields",
    }
    assert any("do not predict closure" in note for note in trend["notes"])


def test_search_tool_resolves_name_to_ccn():
    result = search_hospital.invoke({"name": "Greenbrier Valley"})

    assert result["count"] == 1
    assert result["hospitals"][0]["facility_id"] == "510002"


def test_compare_by_area_county_and_state_truncation(monkeypatch):
    county = compare_hospitals_by_area.invoke(
        {"facility_id": "510001", "scope": "county"}
    )
    assert county["area"] == "MONONGALIA"
    assert county["comparison_count"] == 1
    assert county["returned_count"] == 1
    assert county["truncated"] is False
    assert county["comparison_hospitals"][0]["facility_id"] == "510024"

    # A state with many hospitals: the tool caps what reaches the LLM
    # but reports the true total so the agent does not misdescribe it.
    many = [HOSPITALS["510002"].model_dump()] + [
        {
            **HOSPITALS["510001"].model_dump(),
            "facility_id": f"52{index:04d}",
            "facility_name": f"HOSPITAL {index}",
        }
        for index in range(1, 25)
    ]
    monkeypatch.setattr(access_service, "get_hospitals_by_state", lambda state: many)

    state = compare_hospitals_by_area.invoke(
        {"facility_id": "510002", "scope": "state"}
    )
    assert state["comparison_count"] == 24
    assert state["returned_count"] == agent_tools.MAX_HOSPITALS_FOR_AGENT
    assert state["truncated"] is True

    limited = compare_hospitals_by_area.invoke(
        {"facility_id": "510002", "scope": "state", "limit": 5}
    )
    assert limited["returned_count"] == 5


def test_healthcare_access_combines_cms_and_census(census):
    demographics = get_hospital_demographics.invoke({"facility_id": "510002"})
    assert demographics["county"] == "GREENBRIER"
    assert demographics["total_population"] == 32000
    assert demographics["population_65_plus_percent"] == 25.0
    assert "Census" in demographics["source"]

    access = analyze_healthcare_access.invoke({"facility_id": "510002"})
    assert access["facility_name"].startswith("CAMC GREENBRIER")
    assert access["alternative_hospital_count"] == 0
    assert access["county_demographics"]["available"] is True
    assert access["county_demographics"]["total_population"] == 32000
    assert access["limitations"]


def test_chat_route_returns_agent_answer(monkeypatch):
    monkeypatch.setattr(
        routes, "ask_hospital_agent", lambda message: f"answer to: {message}"
    )

    response = client.post(
        "/agent/chat",
        json={"message": "  Analyze hospital 510002.  "},
    )

    assert response.status_code == 200
    assert response.json() == {"response": "answer to: Analyze hospital 510002."}

# endregion


# region Edge scenarios

def test_indicators_report_missing_fields_and_zero_denominators(cost_reports):
    cost_reports[(2024, "510002")] = [
        cms_row(**{
            "Total Liabilities": "",          # missing in the cost report
            "Total Bed Days Available": "0",  # present but unusable
        })
    ]

    body = client.get("/hospitals/510002/indicators").json()

    assert body["liability_to_asset_ratio"] is None
    assert body["occupancy_rate"] is None
    assert body["operating_margin"] == -20.0
    assert body["missing_fields"] == ["total_liabilities"]


def test_duplicate_reports_in_one_year_pick_the_most_complete_row(cost_reports):
    cost_reports[(2024, "510002")] = [
        cms_row(end="2024-12-31", **{
            "Net Patient Revenue": "",
            "Net Income from Service to Patients": "",
        }),
        cms_row(end="2024-06-30"),
    ]

    body = client.get("/hospitals/510002/indicators").json()

    assert body["fiscal_year_end"] == "2024-06-30"
    assert body["operating_margin"] == -20.0


def test_trend_with_a_single_year_is_insufficient_data(cost_reports):
    cost_reports[(2024, "510002")] = [cms_row()]

    body = client.get("/hospitals/510002/trend").json()

    assert body["years_with_data"] == [2024]
    assert body["years_without_report"] == [2020, 2021, 2022, 2023]
    margin = body["indicator_trends"]["operating_margin"]
    assert margin["direction"] == "insufficient_data"
    assert margin["change"] is None
    assert body["consecutive_negative_operating_margin_years"] == 1


def test_trend_years_outside_cms_coverage_are_reported_not_guessed():
    response = client.get(
        "/hospitals/510002/trend",
        params={"start_year": 2030, "end_year": 2031},
    )

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["years_requested"] == [2030, 2031]
    assert detail["years_unavailable"]["2030"] == "outside CMS coverage (2020-2024)"

    tool = analyze_financial_trend.invoke(
        {"facility_id": "510002", "start_year": 2030, "end_year": 2031}
    )
    assert "No cost report data" in tool["error"]
    assert tool["years_unavailable"][2031].startswith("outside CMS coverage")


def test_trend_rejects_invalid_year_ranges():
    backwards = client.get(
        "/hospitals/510002/trend",
        params={"start_year": 2024, "end_year": 2020},
    )
    assert backwards.status_code == 400
    assert "start_year" in backwards.json()["detail"]

    too_wide = client.get(
        "/hospitals/510002/trend",
        params={"start_year": 1990, "end_year": 2024},
    )
    assert too_wide.status_code == 400
    assert "at most 30 years" in too_wide.json()["detail"]

    out_of_bounds = client.get(
        "/hospitals/510002/indicators", params={"year": 1800}
    )
    assert out_of_bounds.status_code == 422

    tool = analyze_financial_trend.invoke(
        {"facility_id": "510002", "start_year": 2024, "end_year": 2020}
    )
    assert "start_year" in tool["error"]


def test_ambiguous_hospital_name_returns_every_match():
    # The live agent then asks the user which hospital they mean
    # instead of guessing (verified in the live scenarios).
    result = search_hospital.invoke({"name": "Greenbrier"})

    assert result["count"] == 2
    assert {h["facility_id"] for h in result["hospitals"]} == {"510002", "194069"}


def test_search_with_no_match_is_empty_not_an_error():
    assert client.get("/hospitals/search", params={"name": "ZZZNOPE"}).json() == []
    assert search_hospital.invoke({"name": "ZZZNOPE"}) == {
        "query": "ZZZNOPE", "count": 0, "hospitals": [],
    }


def test_chat_route_rejects_blank_or_missing_message():
    assert client.post("/agent/chat", json={"message": "   "}).status_code == 400
    assert client.post("/agent/chat", json={}).status_code == 422


def test_state_normalization_covers_dc_and_puerto_rico():
    assert normalize_state("district of columbia") == "DC"
    assert normalize_state("pr") == "PR"
    assert get_state_fips("DC") == "11"
    assert get_state_fips("PR") == "72"

# endregion


# region Failure scenarios

def test_cms_cost_report_outage_returns_503_and_tool_error(cost_reports):
    for year in DATASET_IDS:
        cost_reports[(year, "510002")] = requests.ConnectionError("CMS down")

    indicators = client.get("/hospitals/510002/indicators")
    assert indicators.status_code == 503
    assert "CMS down" in indicators.json()["detail"]

    trend = client.get("/hospitals/510002/trend")
    assert trend.status_code == 404
    assert set(trend.json()["detail"]["years_unavailable"]) == {
        "2020", "2021", "2022", "2023", "2024"
    }

    tool = analyze_hospital_financials.invoke({"facility_id": "510002"})
    assert tool["error"].startswith("CMS cost report data could not be retrieved")


def test_stale_dataset_id_is_refreshed_from_the_catalog(monkeypatch, cost_reports):
    cost_reports[(2024, "510002")] = [cms_row()]

    def catalog(force_refresh: bool = False):
        if force_refresh:
            return dict(DATASET_IDS)
        return {**DATASET_IDS, 2024: "dataset-2024-rotated-away"}

    monkeypatch.setattr(cost_report_service, "get_cost_report_datasets", catalog)

    response = client.get("/hospitals/510002/indicators", params={"year": 2024})

    assert response.status_code == 200
    assert response.json()["report_year"] == 2024


def test_dataset_id_gone_for_good_returns_503(cost_reports):
    cost_reports[(2024, "510002")] = 404

    response = client.get("/hospitals/510002/indicators", params={"year": 2024})

    assert response.status_code == 503
    assert "dataset ID no longer exists" in response.json()["detail"]


def test_unknown_ccn_is_a_404_and_a_tool_error_not_a_crash():
    assert client.get("/hospitals/000000").status_code == 404
    assert client.get("/hospitals/000000/indicators").status_code == 404

    assert analyze_hospital_financials.invoke({"facility_id": "000000"})["error"] == (
        "Financial data not found"
    )
    assert compare_hospitals_by_area.invoke(
        {"facility_id": "000000", "scope": "county"}
    )["error"] == "Hospital not found"
    assert analyze_healthcare_access.invoke({"facility_id": "000000"})["error"] == (
        "Hospital not found"
    )
    assert get_hospital_demographics.invoke({"facility_id": "000000"})["error"] == (
        "Hospital not found"
    )


def test_invalid_inputs_are_reported_as_errors():
    assert client.get("/hospitals", params={"state": "ZZ"}).status_code == 400

    bad_scope = compare_hospitals_by_area.invoke(
        {"facility_id": "510002", "scope": "planet"}
    )
    assert "scope" in bad_scope["error"]


def test_missing_census_key_degrades_gracefully(monkeypatch):
    # Found live: this used to raise ValueError inside the tool and
    # turn the whole /agent/chat request into a 500.
    monkeypatch.setattr(census_service, "CENSUS_API_KEY", None)

    demographics = get_hospital_demographics.invoke({"facility_id": "510002"})
    assert "CENSUS_API_KEY" in demographics["error"]

    access = analyze_healthcare_access.invoke({"facility_id": "510002"})
    assert access["alternative_hospital_count"] == 0
    assert access["county_demographics"]["available"] is False
    assert "CENSUS_API_KEY" in access["county_demographics"]["error"]


def test_census_outage_or_html_reply_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(census_service, "CENSUS_API_KEY", "offline-test-key")

    def census_down(*args, **kwargs):
        raise requests.ConnectionError("census.gov unreachable")

    monkeypatch.setattr(requests, "get", census_down)
    result = get_hospital_demographics.invoke({"facility_id": "510002"})
    assert "unreachable" in result["error"]

    # Without a valid key the Census API redirects to an HTML page.
    class HtmlResponse(FakeResponse):
        def json(self):
            raise ValueError("Expecting value: line 1 column 1")

    monkeypatch.setattr(requests, "get", lambda *a, **k: HtmlResponse())
    result = get_hospital_demographics.invoke({"facility_id": "510002"})
    assert "unavailable" in result["error"]


def test_territory_without_fips_mapping_degrades_gracefully(census):
    result = get_hospital_demographics.invoke({"facility_id": "650001"})

    assert "GU" in result["error"]

    access = analyze_healthcare_access.invoke({"facility_id": "650001"})
    assert access["county_demographics"]["available"] is False


def test_chat_route_reports_agent_failure_as_502(monkeypatch):
    def broken_agent(message: str) -> str:
        raise RuntimeError("OpenAI unavailable")

    monkeypatch.setattr(routes, "ask_hospital_agent", broken_agent)

    response = client.post("/agent/chat", json={"message": "hello"})

    assert response.status_code == 502
    assert "OpenAI unavailable" in response.json()["detail"]

# endregion
