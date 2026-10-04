from app.common.constants import HOSPITAL_FIELDS
from app.utils.state_utils import normalize_state
from fastapi import APIRouter, HTTPException
from app.models.hospital import Hospital
from app.services.cms_service import (
    get_hospitals_by_state,
    get_hospital_by_id,
    search_hospitals_by_name,
)
from app.models.financial import HospitalFinancialRecord
from app.services.cost_report_service import (
    get_financial_data_by_hospital,
    get_raw_financial_data_by_hospital,
)
from app.models.financial import FinancialIndicators
from app.tools.financial_tools import calculate_financial_indicators
from app.agents.hospital_agent import ask_hospital_agent
from app.agents.agent import AgentRequest, AgentResponse

router = APIRouter()

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

@router.get(
    "/hospitals/{facility_id}/financials",
    response_model=HospitalFinancialRecord,
)
def get_hospital_financials(facility_id: str):
    financial_data = get_financial_data_by_hospital(
        facility_id
    )

    if financial_data is None:
        raise HTTPException(
            status_code=404,
            detail="Financial data not found",
        )

    return financial_data

@router.get("/hospitals/{facility_id}/financials/raw")
def get_raw_hospital_financials(facility_id: str):
    return get_raw_financial_data_by_hospital(facility_id)

@router.get(
    "/hospitals/{facility_id}/indicators",
    response_model=FinancialIndicators,
)
def get_hospital_indicators(facility_id: str):
    financial_data = get_financial_data_by_hospital(
        facility_id
    )

    if financial_data is None:
        raise HTTPException(
            status_code=404,
            detail="Financial data not found",
        )

    return calculate_financial_indicators(
        financial_data
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