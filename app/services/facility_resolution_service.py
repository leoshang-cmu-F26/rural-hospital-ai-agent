"""Resolve an institution in one model-facing call using compact source results."""

import sqlite3
from requests import RequestException
from app.services.cms_service import search_hospitals_by_name, get_hospital_by_id
from app.services.tribal_directory_service import search_tribal_facilities


def _compact_hospital(hospital):
    """Keep only identity, location and type needed by subsequent tools."""
    result = {}
    for field in (
        'facility_id',
        'facility_name',
        'citytown',
        'state',
        'countyparish',
        'hospital_type',
    ):
        result[field] = getattr(hospital, field)
    if hospital.source_provenance:
        result["source_provenance"] = hospital.source_provenance
    return result


def resolve_facility_identity(name=None, state=None, county=None, facility_id=None):
    """Combine local historical lookup and current CMS verification without an LLM hop."""
    # 1. Reject conflicting identification modes rather than dropping user filters.
    if bool(name) == bool(facility_id):
        return {'error': 'Provide either a facility name or a CCN.'}
    if facility_id and (state or county):
        return {'error': 'Use the CCN alone, or supply a name with location filters.'}

    # 2. Read the local snapshot internally; never expose its CCNs as verified IDs.
    historical = None
    historical_available = True
    if name:
        try:
            historical = search_tribal_facilities(name=name, state=state, limit=3)
            if 'error' in historical:
                return historical
        except (OSError, ValueError, sqlite3.Error):
            historical_available = False

    # 3. Always verify present hospital identity using the current hospital dataset.
    hospitals = []
    current_available = True
    try:
        if facility_id:
            hospital = get_hospital_by_id(facility_id)
            if hospital is not None:
                hospitals.append(hospital)
        else:
            hospitals = search_hospitals_by_name(name, state, county)
    except ValueError as exc:
        return {'error': str(exc)}
    except (RequestException, OSError):
        current_available = False

    # 4. Return at most three candidates; a failed source is distinct from no match.
    result = {
        'resolution_status': 'not_found',
        'current_cms_available': current_available,
        'candidate_count': len(hospitals),
        'candidates': [],
        'can_analyze_hospital_financials': False,
    }
    for hospital in hospitals[:3]:
        result['candidates'].append(_compact_hospital(hospital))
    if not current_available:
        result['resolution_status'] = 'unavailable'
    elif len(hospitals) == 1:
        result['resolution_status'] = 'resolved_hospital'
        result['target_hospital'] = result['candidates'].pop()
        result['can_analyze_hospital_financials'] = True
        return result
    elif len(hospitals) > 1:
        result['resolution_status'] = 'ambiguous'
        return result

    # 5. Supply historical types and citations only when current resolution failed.
    if name:
        result['historical_directory_available'] = historical_available
    if historical and historical.get('count'):
        result['historical_matches'] = []
        result['historical_match_count'] = historical['count']
        result['historical_source_date'] = historical['source_created_date']
        for entry in historical['facilities']:
            result['historical_matches'].append(
                {
                    'facility_name': entry['facility_name'],
                    'facility_type': entry['facility_type'],
                    'city': entry['city'],
                    'state': entry['state'],
                    'citation_url': entry['citation_url'],
                }
            )
        result['historical_note'] = (
            'Historical only; current identity/type unverified. County filter was not applied to historical entries. No hospital financial CCN resolved.'
        )
    result['next_step'] = (
        'Clarify name/location, or offer access analysis using a user-confirmed full address. No match does not establish nonexistence.'
    )
    return result
