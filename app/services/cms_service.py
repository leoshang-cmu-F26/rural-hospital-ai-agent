"""CMS hospital retrieval, bounded caches, pagination and location-aware name search."""

import re
import unicodedata
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



def _normalize_search_text(value):
    """Normalize accents, case and punctuation without guessing facility aliases."""
    value = unicodedata.normalize("NFKD", value or "")
    characters = []
    for character in value:
        if not unicodedata.combining(character):
            characters.append(character)
    value = ''.join(characters)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def normalize_county(value):
    """Normalize a county label and reject a missing county name."""
    normalized = _normalize_search_text(value)
    if normalized.endswith(" county"):
        normalized = normalized[:-7].strip()
    if not normalized or normalized == "county":
        raise ValueError("County must not be blank.")
    return normalized


def _query_hospital_rows(params):
    """Fetch explicit pages so a partial response cannot masquerade as unique."""
    # 1. Retrieve complete pages and keep one record per CCN.
    rows, seen = [], set()
    page_size = 500
    for page in range(30):
        response = requests.get(CMS_HOSPITAL_API_URL,
            params={**params, "limit": page_size, "offset": page * page_size}, timeout=30)
        response.raise_for_status()
        batch = response.json().get("results", [])
        added = 0
        for row in batch:
            key = row.get("facility_id")
            if key and key not in seen:
                seen.add(key)
                rows.append(row)
                added += 1
        # 2. Only a completed final page establishes full search coverage.
        if len(batch) < page_size:
            return rows
        if not added:
            raise requests.RequestException("CMS pagination did not advance; search results are incomplete.")
    raise requests.RequestException("CMS search exceeded the supported result limit; narrow the search.")


def get_hospitals_by_state(state: str):
    """Reuse a successful state cache entry or retrieve all CMS result pages."""
    state_code = normalize_state(state)
    # 1. Reuse successful state data before contacting CMS.
    if state_code in STATE_HOSPITAL_CACHE:
        return STATE_HOSPITAL_CACHE[state_code]
    # 2. Cache only after every requested page has completed successfully.
    results = _query_hospital_rows({
        "conditions[0][property]": HOSPITAL_FIELDS.STATE_FIELD,
        "conditions[0][value]": state_code,
        "conditions[0][operator]": "=",
    })
    STATE_HOSPITAL_CACHE[state_code] = results
    return results

def get_hospital_by_id(facility_id: str):

    # Check cache first
    """Resolve a CCN through the memory cache before requesting CMS."""
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

def search_hospitals_by_name(name: str, state: str | None = None,
                             county: str | None = None):
    """Match name tokens with optional strict state/county constraints.

    Punctuation and case are normalized. No fuzzy substitution or invented
    alias is used. Unknown historical names still require clarification.
    """
    # 1. Normalize the name and user constraints without silently dropping them.
    normalized = _normalize_search_text(name)
    if not normalized:
        raise ValueError("Hospital name must not be blank.")
    county_key = None
    if county is not None:
        county_key = normalize_county(county)
    # 2. A supplied state narrows retrieval; otherwise query the most specific token.
    if state is not None:
        state_code = normalize_state(state)
        rows = get_hospitals_by_state(state_code)
    else:
        # Retrieve on the most specific literal token, then match all tokens
        # locally. This tolerates punctuation differences without fuzzy guesses.
        token = max(normalized.split(), key=len)
        rows = _query_hospital_rows({
            "conditions[0][property]": HOSPITAL_FIELDS.FACILITY_NAME_FIELD,
            "conditions[0][value]": token.upper(),
            "conditions[0][operator]": "contains",
        })
    # 3. Match every name token and both location constraints locally.
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
    # 4. Stable ordering helps the user distinguish ambiguous candidates.
    return sorted(hospitals, key=lambda h: (h.facility_name, h.state, h.facility_id))
