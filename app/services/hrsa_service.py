"""County-associated primary-care shortage designations, coverage and TTL caching."""

import threading
from copy import deepcopy

import requests

from cachetools import TTLCache

from app.common.constants import HRSA_FIELDS
from app.utils.state_utils import get_state_name, normalize_state
from app.services import reference_store

from app.services.agent_progress import report_progress

HRSA_PRIMARY_CARE_HPSA_URL = (
    "https://gisportal.hrsa.gov/server/rest/services/" "udsmapper/HPSA/MapServer/0/query"
)

# Cache successful county queries for six hours to limit repeated HRSA
# requests while allowing designations to refresh during the day.
PRIMARY_CARE_HPSA_CACHE = TTLCache(
    maxsize=5000,
    ttl=21600,
)
_PRIMARY_CARE_HPSA_CACHE_LOCK = threading.Lock()


# https://data.hrsa.gov/tools/shortage-area/hpsa-find

# County matching


def _normalize_county_name(
    county: str,
) -> str:
    """
    Normalize county names for comparison.

    Examples:
    GREENBRIER -> GREENBRIER
    Greenbrier County -> GREENBRIER
    """

    normalized = county.strip().upper()

    if normalized.endswith(" COUNTY"):
        normalized = normalized[:-7]

    return normalized.strip()


# Stored or live HPSA retrieval


def get_county_primary_care_hpsa(
    state: str,
    county: str,
) -> dict:
    """
    Retrieve Primary Care HPSA designations associated
    with a county from HRSA.

    This does not assume that the entire county itself
    is designated as a HPSA.
    """

    # 1. Resolve the state name used by HRSA.
    state_name = get_state_name(state)

    target_county = _normalize_county_name(county)

    snapshot = reference_store.read_snapshot('primary_care_hpsa', normalize_state(state))
    if snapshot is not None:
        data = {'features': list(snapshot['records'].values())}
        result = _build_county_summary(state_name, target_county, data)
        result['data_provenance'] = snapshot['data_provenance']
        return result

    cache_key = (state_name.upper(), target_county)

    # Read and copy atomically so callers cannot mutate the cached value.
    with _PRIMARY_CARE_HPSA_CACHE_LOCK:
        cached_result = PRIMARY_CARE_HPSA_CACHE.get(cache_key)
        if cached_result is not None:
            return deepcopy(cached_result)

    # 2. Request Primary Care HPSAs for this state. Filter to the county
    #    below because the service response includes records statewide.
    params = {
        "where": (f"{HRSA_FIELDS.STATE} = " f"'{state_name}'"),
        "outFields": ",".join(
            [
                HRSA_FIELDS.HPSA_SOURCE_ID,
                HRSA_FIELDS.HPSA_NAME,
                HRSA_FIELDS.HPSA_SCORE,
                HRSA_FIELDS.HPSA_STATUS,
                HRSA_FIELDS.HPSA_TYPE,
                HRSA_FIELDS.HPSA_POPULATION_TYPE,
                HRSA_FIELDS.COUNTY,
                HRSA_FIELDS.STATE,
            ]
        ),
        "returnGeometry": "false",
        "f": "json",
    }

    report_progress("Querying HRSA primary-care shortage designations…")
    response = requests.get(
        HRSA_PRIMARY_CARE_HPSA_URL,
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    if "error" in data:
        raise RuntimeError(f"HRSA API error: {data['error']}")

    result = _build_county_summary(state_name, target_county, data)

    # Only cache successful responses; request and API errors propagate.
    with _PRIMARY_CARE_HPSA_CACHE_LOCK:
        PRIMARY_CARE_HPSA_CACHE[cache_key] = deepcopy(result)

    # 5. Return the county-level summary and matching designations.
    return result


# County designation summary


def _build_county_summary(state_name, target_county, data):
    """Summarize the same source fields for live or stored HRSA snapshots."""
    # 3. Keep only designations associated with the requested county.
    matching_designations = []

    for feature in data.get("features", []):
        attributes = feature.get(
            "attributes",
            {},
        )

        hrsa_county = attributes.get(HRSA_FIELDS.COUNTY)

        if not hrsa_county:
            continue

        if _normalize_county_name(hrsa_county) != target_county:
            continue

        matching_designations.append(
            {
                "hpsa_id": attributes.get(HRSA_FIELDS.HPSA_SOURCE_ID),
                "name": attributes.get(HRSA_FIELDS.HPSA_NAME),
                "score": attributes.get(HRSA_FIELDS.HPSA_SCORE),
                "status": attributes.get(HRSA_FIELDS.HPSA_STATUS),
                "type": attributes.get(HRSA_FIELDS.HPSA_TYPE),
                "population_type": attributes.get(HRSA_FIELDS.HPSA_POPULATION_TYPE),
            }
        )

    # 4. Identify active designations and calculate the highest score.
    active_designations = []
    for designation in matching_designations:
        if designation['status'] == 'Designated':
            active_designations.append(designation)

    active_scores = []
    for designation in active_designations:
        if designation['score'] is not None:
            active_scores.append(designation['score'])

    max_hpsa_score = None
    if active_scores:
        max_hpsa_score = max(active_scores)

    result = {
        "state": state_name,
        "county": target_county,
        "has_active_primary_care_hpsa": len(active_designations) > 0,
        "designation_count": len(matching_designations),
        "active_designation_count": len(active_designations),
        "max_hpsa_score": max_hpsa_score,
        "designations": matching_designations,
        "source": "HRSA Health Professional Shortage Areas",
        "discipline": "Primary Care",
    }

    return result
