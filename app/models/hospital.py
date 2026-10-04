from pydantic import BaseModel


class Hospital(BaseModel):
    facility_id: str
    facility_name: str

    address: str | None = None
    citytown: str
    state: str
    zip_code: str
    countyparish: str | None = None

    hospital_type: str