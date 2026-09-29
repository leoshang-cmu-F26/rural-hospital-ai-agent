import requests
from app.models.hospital import Hospital
from app.utils.state_utils import normalize_state

CMS_HOSPITAL_API_URL = (
    "https://data.cms.gov/provider-data/api/1/"
    "datastore/query/xubh-q36u/0"
)


def get_hospitals_by_state(state: str):
    state_code = normalize_state(state)

    params = {
        "conditions[0][property]": "state",
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

    return data["results"]

def get_hospital_by_id(facility_id: str):
    params = {
        "conditions[0][property]": "facility_id",
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

    return Hospital(**results[0])

def search_hospitals_by_name(name: str):
    params = {
        "conditions[0][property]": "facility_name",
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
