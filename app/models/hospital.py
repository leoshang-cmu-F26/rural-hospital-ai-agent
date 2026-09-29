from pydantic import BaseModel


class Hospital(BaseModel):
    facility_id: str
    facility_name: str
    citytown: str
    state: str
    zip_code: str
    hospital_type: str