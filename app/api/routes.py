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

router = APIRouter()

def year_query(
    description: str = "CMS cost-report dataset year",
):
    # A fresh Query() per parameter. FastAPI binds a FieldInfo to the
    # first parameter name it sees, so sharing one instance would make
    # start_year / end_year silently read the "year" query parameter.
    return Query(
        default=None,
        ge=1990,
        le=2100,
        description=description,
    )


# region Hospital API

@router.get("/")
def root():
    return {
        "message": "Rural Hospital AI Agent API is running"
    }


@router.get("/health")
def health_check():
    return {
        "status": "healthy"
    }


@router.get("/hospitals")
def get_hospitals(state: str):
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
def search_hospitals(name: str):
    return search_hospitals_by_name(name)


@router.get(
    "/hospitals/{facility_id}",
    response_model=Hospital
)
def get_hospital(facility_id: str):
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

    return {
        "years": sorted(datasets),
        "datasets": {
            str(year): dataset_id
            for year, dataset_id in sorted(datasets.items())
        },
    }


@router.get(
    "/hospitals/{facility_id}/financials",
    response_model=HospitalFinancialRecord,
)
def get_hospital_financials(
    facility_id: str,
    year: int | None = year_query(),
):
    return _load_financial_record(facility_id, year)


@router.get("/hospitals/{facility_id}/financials/raw")
def get_raw_hospital_financials(
    facility_id: str,
    year: int | None = year_query(),
):
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
    history = _load_financial_history(
        facility_id,
        start_year,
        end_year,
    )

    if not history.records:
        raise HTTPException(
            status_code=404,
            detail={
                "message": (
                    "No cost report data found for this hospital "
                    "in the requested years"
                ),
                "years_requested": history.years_requested,
                "years_without_report": history.years_without_report,
                "years_unavailable": {
                    str(year): reason
                    for year, reason
                    in history.years_unavailable.items()
                },
            },
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


# region Agent API

@router.post(
    "/agent/chat",
    response_model=AgentResponse,
)
def chat_with_agent(request: AgentRequest):
    response = ask_hospital_agent(request.message)

    return AgentResponse(
        response=response
    )

# endregion
