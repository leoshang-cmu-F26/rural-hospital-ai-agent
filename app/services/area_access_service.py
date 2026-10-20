"""Deterministic state/county/ZIP access reports with explicit rural-classification gaps."""

import re
from statistics import median

from app.services.cms_service import get_hospitals_by_state, normalize_county
from app.services.cost_report_service import get_financial_data_by_hospital, get_latest_report_year
from app.services.census_service import get_hospital_demographics
from app.services.hrsa_service import get_county_primary_care_hpsa
from app.services.geocoding_service import geocode_hospital_record
from app.services.distance_service import calculate_distance_miles
from app.services.agent_progress import report_progress
from app.tools.financial_tools import is_rural_hospital
from app.utils.state_utils import normalize_state


def _available(call, *args, **kwargs):
    """Keep one unavailable data source from discarding the other evidence."""
    try:
        value = call(*args, **kwargs)
        if value is None:
            return {'available': False, 'error': 'No record returned.'}
        if 'error' in value:
            return {'available': False, 'error': value['error']}
        return {'available': True, **value}
    except Exception as error:
        return {'available': False, 'error': str(error)}


def analyze_area_access(state, county=None, rural_only=True, year=None, zip_code=None):
    """Analyze eligible hospital locations; county/ZIP restrict targets, not neighbors."""
    # 1. Validate geography before requests; use one cost-report year for all targets.
    state_code = normalize_state(state)
    # ZIP stays a string so leading zeros survive. ZIP+4 in CMS rows maps to ZIP5.
    zip_key = None
    if zip_code is not None:
        if not isinstance(zip_code, str) or not re.fullmatch(r'[0-9]{5}', zip_code.strip()):
            raise ValueError('zip_code must be a five-digit string; supply state separately.')
        zip_key = zip_code.strip()
    county_key = None
    if county is not None:
        county_key = normalize_county(county)
    if year is not None and (isinstance(year, bool) or not isinstance(year, int) or year < 2011):
        raise ValueError('year must be an integer CMS dataset year from 2011 onward.')
    if not isinstance(rural_only, bool):
        raise ValueError('rural_only must be a boolean.')
    report_progress('Retrieving the complete state hospital directory…')
    rows = get_hospitals_by_state(state_code)
    targets = []
    seen = set()
    state_rows = []
    for row in rows:
        facility_id = row.get('facility_id')
        if not facility_id or facility_id in seen or row.get('state', '').upper() != state_code:
            continue
        seen.add(facility_id)
        state_rows.append(row)
        if county_key is not None:
            label = row.get('countyparish')
            if not label or normalize_county(label) != county_key:
                continue
        if zip_key is not None:
            hospital_zip = str(row.get('zip_code') or '').strip()
            if not re.fullmatch(r'[0-9]{5}(?:-[0-9]{4})?', hospital_zip):
                continue
            if hospital_zip[:5] != zip_key:
                continue
        targets.append(row)

    # 2. Rural eligibility is unknown if a report, its classification or source fails.
    classification_year = year
    classification_error = None
    if rural_only and targets and classification_year is None:
        try:
            classification_year = get_latest_report_year()
        except Exception as error:
            classification_error = str(error)
    selected = []
    unknown = []
    urban_count = 0
    for row in targets:
        if not rural_only:
            selected.append(row)
            continue
        report_progress(f"Checking rural classification for {row['facility_name']}…")
        identity = {'facility_id': row['facility_id'], 'facility_name': row['facility_name']}
        try:
            if classification_error:
                raise ValueError(classification_error)
            record = get_financial_data_by_hospital(row['facility_id'], year=classification_year)
            if record is None:
                raise ValueError('No cost report in the selected classification year.')
            rural = is_rural_hospital(record)
            if rural is None:
                raise ValueError('Rural/urban classification is missing or unrecognized.')
            if rural:
                selected.append(row)
            else:
                urban_count += 1
        except Exception as error:
            unknown.append({**identity, 'reason': str(error)})

    # 3. Geocode the state once, including urban/out-of-county alternative hospitals.
    coordinates = {}
    coordinate_errors = {}
    if selected:
        for index, row in enumerate(state_rows, start=1):
            report_progress(f'Locating same-state hospitals: {index}/{len(state_rows)}…')
            try:
                value = geocode_hospital_record(row)
                if value is None:
                    raise ValueError('Coordinates unavailable.')
                coordinates[row['facility_id']] = value
            except Exception as error:
                coordinate_errors[row['facility_id']] = str(error)

    # 4. Query each represented county once; never sum repeated county populations.
    counties = {}
    reports = []
    nearest_distances = []
    distance_available_count = 0
    for row in selected:
        facility_id = row['facility_id']
        label = row.get('countyparish')
        key = None
        if label:
            key = normalize_county(label)
            if key not in counties:
                report_progress(f'Retrieving county evidence for {label}, {state_code}…')
                counties[key] = {
                    'county': label, 'state': state_code,
                    'demographics': _available(get_hospital_demographics, facility_id),
                    'primary_care_hpsa': _available(get_county_primary_care_hpsa, state=state_code, county=label),
                }
        other_count = None
        if key is not None:
            other_count = 0
            for candidate in state_rows:
                candidate_county = candidate.get('countyparish')
                if candidate['facility_id'] != facility_id and candidate_county and normalize_county(candidate_county) == key:
                    other_count += 1

        # 5. Rank all geocoded same-state alternatives locally, outside the model.
        distance = {'available': False, 'error': coordinate_errors.get(facility_id, 'Coordinates unavailable.')}
        origin = coordinates.get(facility_id)
        if origin:
            neighbors = []
            for candidate in state_rows:
                candidate_id = candidate['facility_id']
                point = coordinates.get(candidate_id)
                if candidate_id == facility_id or point is None:
                    continue
                neighbors.append({
                    'facility_id': candidate_id, 'facility_name': candidate['facility_name'],
                    'city': candidate.get('citytown'),
                    'distance_miles': calculate_distance_miles(origin['latitude'], origin['longitude'], point['latitude'], point['longitude']),
                })
            neighbors.sort(key=lambda item: item['distance_miles'])
            distance = {
                'available': True, 'candidate_count': len(neighbors),
                'skipped_geocoding_count': len(coordinate_errors),
                'nearest_hospitals': neighbors[:5],
            }
            distance_available_count += 1
            if neighbors:
                nearest_distances.append(neighbors[0]['distance_miles'])
        reports.append({
            'facility_id': facility_id, 'facility_name': row['facility_name'],
            'city': row.get('citytown'), 'zip_code': row.get('zip_code'), 'county_key': key,
            'other_same_county_hospital_count': other_count,
            'distance_analysis': distance,
        })

    # 6. Summarize coverage explicitly; empty/partial cohorts are not statewide conclusions.
    partial = bool(unknown or coordinate_errors)
    for report in reports:
        if report['county_key'] is None:
            partial = True
    for evidence in counties.values():
        if not evidence['demographics']['available'] or not evidence['primary_care_hpsa']['available']:
            partial = True
    nearest_summary = None
    if nearest_distances:
        nearest_summary = {'hospital_count': len(nearest_distances), 'median_miles': median(nearest_distances),
                           'min_miles': min(nearest_distances), 'max_miles': max(nearest_distances)}
    status = 'complete'
    if partial:
        status = 'partial'
    return {
        'report_kind': 'area_healthcare_access', 'status': status,
        'area': {'state': state_code, 'county': county_key, 'zip_code': zip_key}, 'rural_only': rural_only,
        'classification': {'source': 'CMS Hospital Provider Cost Report: Rural Versus Urban',
                           'dataset_year': classification_year, 'rule': 'R = rural; U = urban; other/missing = unknown',
                           'applied': rural_only},
        'coverage': {'state_hospital_count': len(state_rows), 'area_hospital_count': len(targets),
                     'selected_hospital_count': len(selected), 'excluded_urban_count': urban_count,
                     'unknown_classification_count': len(unknown), 'represented_county_count': len(counties),
                     'distance_available_count': distance_available_count},
        'unknown_classification': unknown, 'counties': counties, 'hospitals': reports,
        'nearest_distance_summary': nearest_summary,
        'limitations': [
            'Rural eligibility is based on the selected cost-report year, not an independent geographic rural definition; unknown classifications are excluded and disclosed.',
            'Targets are current CMS-listed hospitals. This is not a census of all facilities or a population-wide access assessment.',
            'County evidence covers only counties with selected hospitals; counties without hospitals are not assessed. Do not sum county data across hospital rows.',
            'ZIP filters use hospital mailing ZIP5, not a radius, service area or Census ZCTA. No hospital match does not imply no nearby care. County and ZIP filters intersect when both supplied.',
            'Population and HPSA evidence remain county-level, not ZIP-level. A ZIP may span multiple counties; only counties of selected hospitals are represented.',
            'County population is not hospital catchment or tribal population. HPSA designations may apply to a population group or service area, not the entire county.',
            'Distances are straight-line miles, not driving time. Cross-state hospitals are excluded; urban and out-of-county same-state neighbors are included.',
            'Hospitals without coordinates are excluded from rankings. No capacity, service equivalence, eligibility, closure risk or overall access score is established.',
        ],
    }
