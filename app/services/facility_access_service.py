"""Location-based access evidence for facilities without a hospital CCN."""

import sqlite3
import re
import requests

from app.services.census_service import get_county_demographics
from app.services.hrsa_service import get_county_primary_care_hpsa
from app.services.cms_service import get_hospitals_by_state
from app.services.geocoding_service import geocode_hospital_record
from app.services.distance_service import calculate_distance_miles
from app.utils.state_utils import normalize_state, get_state_fips
from app.services.agent_progress import report_progress

GEOGRAPHIES_URL = 'https://geocoding.geo.census.gov/geocoder/geographies/address'
LIMITATIONS = [
    'The facility name and address are user supplied; an address match does not verify facility identity, operation, or tribal affiliation.',
    'County demographics and HPSA evidence do not describe tribal population, membership, eligibility, or the facility service area.',
    'Hospital candidates are CMS-listed same-state facilities; cross-state hospitals may be closer.',
    'Distances are straight-line miles, not driving distance or travel time. Capacity, services, and eligibility are not assessed.',
    'No CMS hospital financial report or rural classification is inferred for the target facility.',
    'The target has no resolved CCN; the candidate list may include a CMS record of the same facility and is not a verified list of alternatives.',
]


def _unavailable(message):
    """Represent missing evidence explicitly instead of substituting zero."""
    return {'available': False, 'error': message}


def _evidence(lookup, **kwargs):
    """Keep a failed evidence lookup separate from other available sections."""
    try:
        data = lookup(**kwargs)
        if data is None:
            return _unavailable('Data unavailable.')
        if 'error' in data:
            return _unavailable(data['error'])
        available_evidence = {}
        for copied_key, copied_value in (data).items():
            available_evidence[copied_key] = copied_value
        available_evidence['available'] = True

        return available_evidence
    except (requests.RequestException, ValueError) as error:
        return _unavailable(str(error))


def analyze_facility_access(
    facility_name: str,
    address: str,
    city: str,
    state: str,
    zip_code: str,
    address_verified: bool = False,
) -> dict:
    """Analyze a user-confirmed physical address without inventing a CCN."""
    # 1. Require explicit user confirmation before using the facility address.
    # This records the user's confirmation, not independent identity verification.
    if address_verified is not True:
        return {
            'error': 'Ask the user to confirm the facility address is verified before analysis.'
        }

    # 2. Validate every required text field, then remove surrounding whitespace.
    values = [facility_name, address, city, state, zip_code]
    normalized_values = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            return {
                'error': 'Facility name, street address, city, state, and ZIP code are required.'
            }
        normalized_values.append(value.strip())

    facility_name, address, city, state, zip_code = normalized_values

    # 3. Normalize the state, resolve its Census FIPS code, and validate the ZIP.
    try:
        state = normalize_state(state)
        state_fips = get_state_fips(state)
    except ValueError as error:
        return {'error': str(error)}
    if not re.fullmatch(r'\d{5}(-\d{4})?', zip_code):
        return {
            'error': 'ZIP code must have five digits, optionally followed by a four-digit extension.'
        }

    # 4. Initialize independent evidence sections as unavailable. Early returns
    # retain the target address and limitations without inventing missing data.
    result = {
        'target_facility': {
            'facility_name': facility_name,
            'address': address,
            'city': city,
            'state': state,
            'zip_code': zip_code,
            'address_verification': 'user_confirmed',
        },
        'location': _unavailable('Address not resolved.'),
        'county_demographics': _unavailable('County not resolved.'),
        'primary_care_hpsa': _unavailable('County not resolved.'),
        'distance_analysis': _unavailable('Address not resolved.'),
        'limitations': list(LIMITATIONS),
    }

    # 5. Ask Census for the address coordinates and containing geographies.
    # A match locates the address; it does not establish who operates there.
    try:
        report_progress("Matching the supplied address and resolving its county…")
        response = requests.get(
            GEOGRAPHIES_URL,
            params={
                'street': address,
                'city': city,
                'state': state,
                'zip': zip_code,
                'benchmark': 'Public_AR_Current',
                'vintage': 'Current_Current',
                'format': 'json',
            },
            timeout=30,
        )
        response.raise_for_status()
        matches = response.json().get('result', {}).get('addressMatches', [])

        # 6. Require exactly one match. Never guess between multiple locations.
        if len(matches) != 1:
            result['location'] = _unavailable(
                'No unique address match. Ask the user to check the physical street address.'
            )
            return result
        match = matches[0]

        # 7. Validate the returned coordinates and state before using them.
        # Census uses x for longitude and y for latitude.
        coords = match.get('coordinates', {})
        if coords.get('x') is None or coords.get('y') is None:
            return result
        components = match.get('addressComponents', {})
        if components.get('state', state).upper() != state:
            result['location'] = _unavailable(
                'Matched state differs from supplied state; confirm the address.'
            )
            return result
        latitude, longitude = float(coords['y']), float(coords['x'])
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return result

        # 8. Use county evidence only when Census returns one unambiguous county
        # in the supplied state. Missing county data still permits distance work.
        counties = match.get('geographies', {}).get('Counties', [])
        if len(counties) == 1:
            county = counties[0]
        else:
            county = None
        if county and county.get('STATE') != state_fips:
            result['location'] = _unavailable(
                'Matched county state differs from supplied state; confirm the address.'
            )
            return result
        result['location'] = {
            'available': True,
            'latitude': latitude,
            'longitude': longitude,
            'matched_address': match.get('matchedAddress'),
            'source': 'U.S. Census Bureau Geocoder',
        }

        # 9. Retrieve county demographics and primary-care HPSA independently.
        # These describe county context, not tribal population or a service area.
        if county and county.get('NAME'):
            result['location']['county'] = county['NAME']
            result['location']['county_geoid'] = county.get('GEOID')
            result['county_demographics'] = _evidence(
                get_county_demographics, state_fips=state_fips, county_name=county['NAME']
            )
            result['primary_care_hpsa'] = _evidence(
                get_county_primary_care_hpsa, state=state, county=county['NAME']
            )
    except (requests.RequestException, ValueError) as error:
        # Without usable target coordinates, distance ranking cannot proceed.
        result['location'] = _unavailable(str(error))
        return result

    # 10. Retrieve same-state CMS hospitals and exclude missing/duplicate CCNs.
    # The target has no resolved CCN, so its own CMS record may remain a candidate.
    try:
        candidates = []
        skipped = 0
        seen = set()
        report_progress("Retrieving same-state hospital candidates…")
        for hospital in get_hospitals_by_state(state):
            facility_id = hospital.get('facility_id')
            if not facility_id or facility_id in seen:
                continue
            seen.add(facility_id)

            # 11. Reuse hospital coordinate caches. Count unmatched hospitals
            # separately instead of assigning them an invented location/distance.
            try:
                report_progress(f"Locating hospital {len(seen)}; calculating distances…")
                hospital_coords = geocode_hospital_record(hospital)
            except requests.RequestException:
                hospital_coords = None
            if hospital_coords is None:
                skipped += 1
                continue

            # 12. Calculate Haversine straight-line miles from the target address.
            distance_miles = calculate_distance_miles(
                latitude,
                longitude,
                hospital_coords['latitude'],
                hospital_coords['longitude'],
            )
            distance_candidate = {}
            for copied_key, copied_value in (hospital_coords).items():
                distance_candidate[copied_key] = copied_value
            distance_candidate['distance_miles'] = distance_miles

            candidate = distance_candidate
            candidates.append(candidate)

        # 13. Rank candidates by distance, with CCN as a deterministic tie-breaker.
        # Return up to five while retaining counts for the whole ranking pool.
        candidates.sort(key=lambda item: (item['distance_miles'], item['facility_id']))
        nearest_hospitals = candidates[:5]
        result['distance_analysis'] = {
            'available': True,
            'candidate_scope': 'same_state',
            'candidate_count': len(candidates),
            'skipped_geocoding_count': skipped,
            'returned_count': len(nearest_hospitals),
            'nearest_hospitals': nearest_hospitals,
            'distance_unit': 'miles',
            'distance_method': 'Haversine straight-line distance',
            'source': 'CMS Hospital General Information; U.S. Census Bureau Geocoder',
        }
    except (requests.RequestException, sqlite3.Error, ValueError) as error:
        # A distance lookup/cache failure does not discard existing county data.
        result['distance_analysis'] = _unavailable(str(error))

    # 14. Return all available evidence with explicit availability and limitations.
    return result
