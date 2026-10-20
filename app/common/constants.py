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

# See https://api.census.gov/data/2024/acs/acs5/profile/variables.html,
@dataclass(frozen=True)
class _CensusFields:
    TOTAL_POPULATION_FIELD: str = "DP05_0001E"
    AGE_65_PLUS_FIELD: str = "DP05_0024E"
    AGE_65_PLUS_PERCENT_FIELD: str = "DP05_0024PE"


# See https://gisportal.hrsa.gov/server/rest/services/udsmapper/HPSA/MapServer/0
@dataclass(frozen=True)
class _HRSAFields:
    HPSA_SOURCE_ID: str = "HPSA_SOURCE_ID"
    HPSA_NAME: str = "HPSA_NM"
    HPSA_SCORE: str = "HPSA_SCORE"
    HPSA_STATUS: str = "HPSA_STATUS_DESC"
    HPSA_TYPE: str = "HPSA_TYP_DESC"
    HPSA_POPULATION_TYPE: str = "HPSA_POPULATION_TYP_DESC"
    COUNTY: str = "COUNTY_NM"
    STATE: str = "STATE_NM"


HOSPITAL_FIELDS = _HospitalFields()
SCOPE_FIELDS = _ScopeFields()
CENSUS_FIELDS = _CensusFields()
HRSA_FIELDS = _HRSAFields()

