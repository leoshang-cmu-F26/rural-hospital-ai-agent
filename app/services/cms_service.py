import requests
from app.common.constants import HOSPITAL_FIELDS
from app.models.hospital import Hospital
from app.utils.state_utils import normalize_state
from cachetools import TTLCache

# https://data.cms.gov/provider-data/docs
CMS_HOSPITAL_API_URL = (
    "https://data.cms.gov/provider-data/api/1/"
    "datastore/query/xubh-q36u/0"
)

# region Cache

STATE_HOSPITAL_CACHE = TTLCache(
    maxsize=100,
    ttl=3600,
)

HOSPITAL_ID_CACHE = TTLCache(
    maxsize=1000,
    ttl=3600,
)

# endregion


def get_hospitals_by_state(state: str):
    state_code = normalize_state(state)

    # Check cache first
    if state_code in STATE_HOSPITAL_CACHE:
        return STATE_HOSPITAL_CACHE[state_code]

    # CMS's indexed condition query parameters map to its conditions array:
    # https://data.cms.gov/provider-data/api/1
    params = {
        "conditions[0][property]": HOSPITAL_FIELDS.STATE_FIELD,
        "conditions[0][value]": state_code,
        "conditions[0][operator]": "=",
    }

    response = requests.get(
        CMS_HOSPITAL_API_URL,
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()
    results = data.get("results", [])

    # Save result
    STATE_HOSPITAL_CACHE[state_code] = results

    return results

def get_hospital_by_id(facility_id: str):
    
    # Check cache first
    if facility_id in HOSPITAL_ID_CACHE:
        return HOSPITAL_ID_CACHE[facility_id]

    params = {
        "conditions[0][property]": HOSPITAL_FIELDS.FACILITY_ID_FIELD,
        "conditions[0][value]": facility_id,
        "conditions[0][operator]": "=",
    }

    response = requests.get(
        CMS_HOSPITAL_API_URL,
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()
    results = data["results"]

    if not results:
        return None

    hospital = Hospital(**results[0])

    HOSPITAL_ID_CACHE[facility_id] = hospital

    return hospital

def search_hospitals_by_name(name: str):
    params = {
        "conditions[0][property]": HOSPITAL_FIELDS.FACILITY_NAME_FIELD,
        "conditions[0][value]": name.upper(),
        "conditions[0][operator]": "contains",
        "limit": 20,
    }

    response = requests.get(
        CMS_HOSPITAL_API_URL,
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()
    results = data["results"]

    return [
        Hospital(**hospital)
        for hospital in results
    ]
