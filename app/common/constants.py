from dataclasses import dataclass


@dataclass(frozen=True)
class _HospitalFields:
    FACILITY_ID_FIELD: str = "facility_id"
    FACILITY_NAME_FIELD: str = "facility_name"
    ADDRESS_FIELD: str = "address"
    CITYTOWN_FIELD: str = "citytown"
    ZIP_CODE_FIELD: str = "zip_code"
    STATE_FIELD: str = "state"
    COUNTY_PARISH_FIELD: str = "countyparish"
    HOSPITAL_TYPE_FIELD: str = "hospital_type"
    COUNTY_FIELD: str = "county"

@dataclass(frozen=True)
class _ScopeFields:
    COUNTY: str = "county"
    ZIP: str = "zip"
    STATE: str = "state"


HOSPITAL_FIELDS = _HospitalFields()
SCOPE_FIELDS = _ScopeFields()