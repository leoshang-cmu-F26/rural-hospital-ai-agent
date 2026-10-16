from pydantic import BaseModel, Field
from app.services.chat_context import HistoryMessage, CurrentFacility, MAX_HISTORY_MESSAGES


class AgentRequest(BaseModel):
    message: str
    history: list[HistoryMessage] = Field(default_factory=list, max_length=MAX_HISTORY_MESSAGES)
    current_facility: CurrentFacility | None = None
    comparison_facilities: list[CurrentFacility] = Field(default_factory=list, max_length=2)


class AgentResponse(BaseModel):
    response: str