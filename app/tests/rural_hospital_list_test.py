"""Offline contracts for compact rural lists and their HTTP endpoint."""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.services import rural_hospital_service as service


@pytest.fixture
def stored(monkeypatch):
    rows = []
    reports = {}
    for index, code in enumerate(["R", "U", None, "R", "R", "R", "R", "R"]):
        ccn = str(index).zfill(6)
        rows.append(
            {
                "facility_id": ccn,
                "facility_name": f"Hospital {index}",
                "state": "WI",
                "countyparish": "Juneau",
                "zip_code": "53948-1234",
                "citytown": "Mauston",
            }
        )
        reports[ccn] = [{"Rural Versus Urban": code}]
    monkeypatch.setattr(service, "get_hospitals_by_state", lambda state: rows)
    monkeypatch.setattr(service, "get_latest_report_year", lambda: 2024)
    monkeypatch.setattr(service.financial_store, "data_mode", lambda: "database_only")
    batch = Mock(return_value=reports)
    monkeypatch.setattr(service, "_state_reports", batch)
    monkeypatch.setattr(
        service,
        "get_financial_data_by_hospital",
        Mock(side_effect=AssertionError("No per-hospital fetch")),
    )
    return batch


def test_default_limit_and_single_batch(stored):
    result = service.list_rural_hospitals("Wisconsin")
    assert result["returned_count"] == 5
    assert result["confirmed_rural_count"] == 6
    assert result["unknown_classification_count"] == 1
    assert result["classification_year"] == 2024
    assert result["storage"] == "postgresql_snapshot"
    stored.assert_called_once_with("WI", 2024)


def test_location_intersection_and_zip_plus_four(stored):
    result = service.list_rural_hospitals("WI", "Juneau County", "53948", limit=2)
    assert result["returned_count"] == 2
    assert service.list_rural_hospitals("WI", "Other", "53948")["returned_count"] == 0
    assert service.list_rural_hospitals("WI", zip_code="00001")["returned_count"] == 0


@pytest.mark.parametrize(
    "options",
    [
        {"limit": 0},
        {"limit": True},
        {"limit": 51},
        {"zip_code": "1234"},
        {"zip_code": 12345},
        {"year": True},
        {"year": 2010},
    ],
)
def test_invalid_filters(options):
    with pytest.raises(ValueError):
        service.list_rural_hospitals("WI", **options)


def test_uncovered_is_not_empty_list(stored):
    stored.return_value = None
    with pytest.raises(service.financial_store.FinancialStoreUnavailable):
        service.list_rural_hospitals("WI")


def test_batch_query_preserves_duplicate_reports(monkeypatch):
    query = Mock(
        return_value=[({"Provider CCN": "520109"},), ({"Provider CCN": "520109"},)]
    )
    monkeypatch.setattr(service.financial_store, "_read", query)
    assert len(service._state_reports("WI", 2024)["520109"]) == 2
    assert query.call_args.args[1] == ("WI", 2024)


def test_http_static_route_and_tool_registration(stored):
    from fastapi import FastAPI
    from app.api.routes import router
    from app.tools.agent_tools import HOSPITAL_AGENT_TOOLS

    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/hospitals/rural", params={"state": "WI"})
        assert response.status_code == 200
        assert response.json()["returned_count"] == 5
        assert (
            client.get(
                "/hospitals/rural", params={"state": "WI", "limit": 51}
            ).status_code
            == 422
        )
        assert client.get("/hospitals/rural").status_code == 422
    names = []
    for tool in HOSPITAL_AGENT_TOOLS:
        names.append(tool.name)
    assert "list_rural_hospitals" in names
