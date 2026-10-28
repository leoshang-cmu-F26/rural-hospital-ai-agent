"""Typed CMS hospital identity; CCNs remain strings to preserve leading zeros."""

from pydantic import BaseModel


class Hospital(BaseModel):
    """CMS-listed hospital identity and administrative location."""

    facility_id: str
    facility_name: str
    source_provenance: dict | None = None

    address: str | None = None
    citytown: str
    state: str
    zip_code: str
    countyparish: str | None = None

    hospital_type: str
