"""CMS hospital directories, snapshot policy and location-aware name search."""

import re
import unicodedata
import requests
from app.common.constants import HOSPITAL_FIELDS
from app.models.hospital import Hospital
from app.utils.state_utils import normalize_state
from cachetools import TTLCache
from copy import deepcopy
from app.services import reference_store

# https://data.cms.gov/provider-data/docs
CMS_HOSPITAL_API_URL = "https://data.cms.gov/provider-data/api/1/" "datastore/query/xubh-q36u/0"

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


# Search text normalization


def _normalize_search_text(value):
    """Normalize accents, case and punctuation without guessing aliases."""
    value = unicodedata.normalize("NFKD", value or "")
    characters = []
    for character in value:
        if not unicodedata.combining(character):
            characters.append(character)
    value = "".join(characters)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def normalize_county(value):
    """Normalize a county label and reject an empty county name."""
    normalized = _normalize_search_text(value)
    if normalized.endswith(" county"):
        normalized = normalized[:-7].strip()
    if not normalized or normalized == "county":
        raise ValueError("County must not be blank.")
    return normalized


# Complete directory retrieval


def _query_hospital_rows(params):
    """Fetch explicit pages so a partial response cannot masquerade as unique."""
    rows = []
    seen = set()
    page_size = 500
    for page in range(30):
        page_parameters = {}
        for copied_key, copied_value in (params).items():
            page_parameters[copied_key] = copied_value
        page_parameters['limit'] = page_size
        page_parameters['offset'] = page * page_size

        response = requests.get(CMS_HOSPITAL_API_URL, params=page_parameters, timeout=30)
        response.raise_for_status()
        batch = response.json().get("results", [])
        added = 0
        for row in batch:
            key = row.get("facility_id")
            if key and key not in seen:
                seen.add(key)
                rows.append(row)
                added += 1
        if len(batch) < page_size:
            return rows
        if not added:
            raise requests.RequestException(
                "CMS pagination did not advance; search results are incomplete."
            )
    raise requests.RequestException(
        "CMS search exceeded the supported result limit; narrow the search."
    )


# State and CCN lookup


def get_hospitals_by_state(state: str):
    """Read an imported state directory or use the configured live path."""
    state_code = normalize_state(state)
    snapshot = reference_store.read_snapshot('hospital_directory', state_code)
    if snapshot is not None:
        results = []
        for raw in snapshot['records'].values():
            hospital_record = {}
            for copied_key, copied_value in (deepcopy(raw)).items():
                hospital_record[copied_key] = copied_value
            hospital_record['source_provenance'] = snapshot['data_provenance']

            results.append(hospital_record)
        return results
    if state_code in STATE_HOSPITAL_CACHE:
        return STATE_HOSPITAL_CACHE[state_code]
    results = _query_hospital_rows(
        {
            "conditions[0][property]": HOSPITAL_FIELDS.STATE_FIELD,
            "conditions[0][value]": state_code,
            "conditions[0][operator]": "=",
        }
    )
    STATE_HOSPITAL_CACHE[state_code] = results
    return results


def get_hospital_by_id(facility_id: str):
    # In snapshot mode an unimported CCN is unknown, never proven nonexistent.
    """Resolve a hospital CCN without guessing outside imported coverage."""
    if reference_store.data_mode() != 'live':
        cached = HOSPITAL_ID_CACHE.get(facility_id)
        if cached is not None and cached.source_provenance:
            return cached
        try:
            raw = reference_store.hospital_by_id(facility_id)
        except reference_store.ReferenceDataUnavailable:
            if reference_store.data_mode() == 'database_only':
                raise
            raw = None
        if raw is not None:
            hospital = Hospital(**raw)
            HOSPITAL_ID_CACHE[facility_id] = hospital
            return hospital

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


# Name and location matching


def search_hospitals_by_name(name: str, state: str | None = None, county: str | None = None):
    """Match name tokens with optional strict state/county constraints.

    Punctuation and case are normalized. No fuzzy substitution or invented
    alias is used. Unknown historical names still require clarification.
    """
    if state is None and reference_store.data_mode() == 'database_only':
        raise ValueError(
            'Provide a state for name lookup: only imported state directories are available, not a complete national search.'
        )
    normalized = _normalize_search_text(name)
    if not normalized:
        raise ValueError("Hospital name must not be blank.")

    county_key = None
    if county is not None:
        county_key = normalize_county(county)

    if state is not None:
        state_code = normalize_state(state)
        rows = get_hospitals_by_state(state_code)
    else:
        # Retrieve on the most specific literal token, then match all tokens
        # locally. This tolerates punctuation differences without fuzzy guesses.
        token = max(normalized.split(), key=len)
        rows = _query_hospital_rows(
            {
                "conditions[0][property]": HOSPITAL_FIELDS.FACILITY_NAME_FIELD,
                "conditions[0][value]": token.upper(),
                "conditions[0][operator]": "contains",
            }
        )

    hospitals = []
    for row in rows:
        row_name = _normalize_search_text(row.get("facility_name"))

        all_tokens_match = True
        for token in normalized.split():
            if token not in row_name.split():
                all_tokens_match = False
                break
        if not all_tokens_match:
            continue

        if state is not None and row.get("state", "").upper() != state_code:
            continue

        row_county = _normalize_search_text(row.get("countyparish"))
        if row_county.endswith(" county"):
            row_county = row_county[:-7].strip()
        if county_key is not None and row_county != county_key:
            continue

        hospitals.append(Hospital(**row))

    return sorted(hospitals, key=lambda h: (h.facility_name, h.state, h.facility_id))
