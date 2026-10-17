"""HTTP endpoints for hospital lookup, financial analytics and streamed agent chat."""

from fastapi.responses import StreamingResponse
from app.services.chat_stream import stream_agent_events
import logging
from fastapi import APIRouter, HTTPException, Query

from app.agents.agent import AgentRequest, AgentResponse
from app.agents.hospital_agent import ask_hospital_agent
from app.common.constants import HOSPITAL_FIELDS
from app.models.financial import (
    FinancialHistory,
    FinancialIndicators,
    FinancialTrend,
    HospitalFinancialRecord,
)
from app.models.hospital import Hospital
from app.services.cms_service import (
    get_hospital_by_id,
    get_hospitals_by_state,
    search_hospitals_by_name,
)
from app.services.cost_report_service import (
    CostReportUnavailableError,
    get_cost_report_datasets,
    get_financial_data_by_hospital,
    get_financial_history_by_hospital,
    get_raw_financial_data_by_hospital,
)
from app.tools.financial_tools import calculate_financial_indicators
from app.tools.trend_tools import build_financial_trend
from app.utils.state_utils import normalize_state

logger = logging.getLogger(__name__)
router = APIRouter()

def year_query(
    description: str = "CMS cost-report dataset year",
):
    # A fresh Query() per parameter. FastAPI binds a FieldInfo to the
    # first parameter name it sees, so sharing one instance would make
    # start_year / end_year silently read the "year" query parameter.
    """Build a fresh validated dataset-year query parameter for each endpoint."""
    return Query(
        default=None,
        ge=1990,
        le=2100,
        description=description,
    )


# region Hospital API

@router.get("/")
def root():
    """Describe the running API without invoking the model or external services."""
    return {
        "message": "Rural Hospital AI Agent API is running"
    }


@router.get("/health")
def health_check():
    """Return a lightweight application health response."""
    return {
        "status": "healthy"
    }


@router.get("/hospitals")
def get_hospitals(state: str):
    """Normalize the state and return CMS hospitals for that state."""
    try:
        state_code = normalize_state(state)
        hospitals = get_hospitals_by_state(state_code)

        return {
            HOSPITAL_FIELDS.STATE_FIELD: state_code,
            "count": len(hospitals),
            "hospitals": hospitals,
        }

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        )


@router.get(
    "/hospitals/search",
    response_model=list[Hospital]
)
def search_hospitals(name: str, state: str | None = None, county: str | None = None):
    """Search CMS hospital names while preserving supplied state and county filters."""
    try:
        return search_hospitals_by_name(name, state=state, county=county)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.get(
    "/hospitals/{facility_id}",
    response_model=Hospital
)
def get_hospital(facility_id: str):
    """Return the requested CMS hospital or an explicit not-found response."""
    hospital = get_hospital_by_id(facility_id)

    if hospital is None:
        raise HTTPException(
            status_code=404,
            detail="Hospital not found"
        )

    return hospital

# endregion


# region Financial API

def _load_financial_record(
    facility_id: str,
    year: int | None,
) -> HospitalFinancialRecord:
    """Translate single-report retrieval failures into consistent HTTP errors."""
    try:
        financial_data = get_financial_data_by_hospital(
            facility_id,
            year=year,
        )

    except CostReportUnavailableError as error:
        raise HTTPException(
            status_code=503,
            detail=str(error),
        )

    if financial_data is None:
        raise HTTPException(
            status_code=404,
            detail="Financial data not found",
        )

    return financial_data


def _load_financial_history(
    facility_id: str,
    start_year: int | None,
    end_year: int | None,
):
    """Validate the year range and retrieve multi-year reports for API endpoints."""
    try:
        return get_financial_history_by_hospital(
            facility_id,
            start_year=start_year,
            end_year=end_year,
        )

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        )

    except CostReportUnavailableError as error:
        raise HTTPException(
            status_code=503,
            detail=str(error),
        )


@router.get("/datasets/cost-reports")
def list_cost_report_datasets():
    """
    CMS cost-report dataset IDs currently known to the service,
    one per report year. Useful for checking that discovery from
    the CMS catalog is working.
    """
    datasets = get_cost_report_datasets()

    dataset_rows = {}
    for (year, dataset_id) in sorted(datasets.items()):
        dataset_rows[str(year)] = dataset_id
    return {
        "years": sorted(datasets),
        "datasets": dataset_rows,
    }


@router.get(
    "/hospitals/{facility_id}/financials",
    response_model=HospitalFinancialRecord,
)
def get_hospital_financials(
    facility_id: str,
    year: int | None = year_query(),
):
    """Return the selected parsed CMS cost report."""
    return _load_financial_record(facility_id, year)


@router.get("/hospitals/{facility_id}/financials/raw")
def get_raw_hospital_financials(
    facility_id: str,
    year: int | None = year_query(),
):
    """Return source report fields for inspection without changing their meaning."""
    try:
        return get_raw_financial_data_by_hospital(
            facility_id,
            year=year,
        )

    except CostReportUnavailableError as error:
        raise HTTPException(
            status_code=503,
            detail=str(error),
        )


@router.get(
    "/hospitals/{facility_id}/financials/history",
    response_model=FinancialHistory,
)
def get_hospital_financial_history(
    facility_id: str,
    start_year: int | None = year_query("First dataset year"),
    end_year: int | None = year_query("Last dataset year"),
):
    """Return multi-year reports with missing and unavailable years separated."""
    history = _load_financial_history(
        facility_id,
        start_year,
        end_year,
    )

    return FinancialHistory(
        facility_id=history.facility_id,
        years_requested=history.years_requested,
        years_with_data=history.years_with_data,
        years_without_report=history.years_without_report,
        years_unavailable=history.years_unavailable,
        records=history.records,
    )


@router.get(
    "/hospitals/{facility_id}/indicators",
    response_model=FinancialIndicators,
)
def get_hospital_indicators(
    facility_id: str,
    year: int | None = year_query(),
):
    """Compute indicators from the selected source report."""
    return calculate_financial_indicators(
        _load_financial_record(facility_id, year)
    )


@router.get(
    "/hospitals/{facility_id}/trend",
    response_model=FinancialTrend,
)
def get_hospital_financial_trend(
    facility_id: str,
    start_year: int | None = year_query("First dataset year"),
    end_year: int | None = year_query("Last dataset year"),
):
    """Build deterministic trend evidence from retrieved yearly reports."""
    history = _load_financial_history(
        facility_id,
        start_year,
        end_year,
    )

    if not history.records:
        unavailable_years = {}
        for (year, reason) in history.years_unavailable.items():
            unavailable_years[str(year)] = reason
        raise HTTPException(
            status_code=404,
            detail={
                "message": (
                    "No cost report data found for this hospital "
                    "in the requested years"
                ),
                "years_requested": history.years_requested,
                "years_without_report": history.years_without_report,
                "years_unavailable": unavailable_years,
            },
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


# region Agent API

@router.post(
    "/agent/chat",
    response_model=AgentResponse,
)
def chat_with_agent(request: AgentRequest):
    """Run one chat request with bounded prior context and return the final answer."""
    message = request.message.strip()

    if not message:
        raise HTTPException(
            status_code=400,
            detail="message must not be blank",
        )

    # Forward bounded history and only include a comparison pair when present.
    options = {
        "history": request.history,
        "current_facility": request.current_facility,
    }
    if request.comparison_facilities:
        options["comparison_facilities"] = request.comparison_facilities

    try:
        response = ask_hospital_agent(message, **options)

    # The agent run spans OpenAI, LangGraph and every tool; any
    # uncaught exception there would otherwise surface as a bare
    # 500 and the chat UI would only show "Agent request failed."
    except Exception as error:  # noqa: BLE001
        logger.exception("Agent request failed")

        raise HTTPException(
            status_code=502,
            detail=(
                "The AI agent could not complete the request: "
                f"{type(error).__name__}: {error}"
            ),
        )

    return AgentResponse(
        response=response
    )

# endregion


@router.post("/agent/chat/stream")
def chat_with_agent_stream(request: AgentRequest):
    """Stream public progress, evidence metadata and the final chat answer."""
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message must not be blank")
    # Stream the same validated conversation state as the non-streaming route.
    options = {
        "history": request.history,
        "current_facility": request.current_facility,
    }
    if request.comparison_facilities:
        options["comparison_facilities"] = request.comparison_facilities
    return StreamingResponse(
        stream_agent_events(message, ask_hospital_agent, **options),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
