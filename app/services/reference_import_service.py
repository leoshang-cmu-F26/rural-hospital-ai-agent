"""Explicit state reference-data imports; no LLM, no request-time schema changes."""

from datetime import datetime, timezone
import json
import math
import sqlite3

import requests

from app.common.constants import HOSPITAL_FIELDS, HRSA_FIELDS
from app.services import reference_store as store
from app.services.cms_service import _query_hospital_rows, CMS_HOSPITAL_API_URL
from app.services.census_service import CENSUS_API_URL
from app.services.hrsa_service import HRSA_PRIMARY_CARE_HPSA_URL
from app.services.geocoding_service import geocode_address, CENSUS_GEOCODER_URL
from app.services.coordinate_cache import (
    read_coordinate_cache,
    write_coordinate_cache,
    COORDINATE_DB_PATH,
)
from app.utils.state_utils import get_state_name, normalize_state

# Hospital directory import


def import_directory(state):
    # Complete CMS pagination is reused; partial responses never publish.
    """Validate and publish the complete state hospital directory."""
    rows = _query_hospital_rows(
        {
            'conditions[0][property]': HOSPITAL_FIELDS.STATE_FIELD,
            'conditions[0][value]': state,
            'conditions[0][operator]': '=',
        }
    )
    records = {}
    for row in rows:
        if row.get('state') != state or not row.get('facility_id'):
            raise ValueError('Hospital directory contains invalid/out-of-state rows.')
        records[row['facility_id']] = row
    if not records:
        raise ValueError('State directory unexpectedly empty; previous snapshot retained.')
    result = store.publish(
        'hospital_directory', state, records, CMS_HOSPITAL_API_URL, datetime.now(timezone.utc)
    )
    return records, result


# County population import


def fetch_demographics(state):
    """Import county ACS estimates/MOEs and dated AHRF workforce ratios."""
    from app.services.county_statistics_import import fetch_county_statistics

    return fetch_county_statistics(state)


# Complete HPSA feature retrieval


def fetch_hpsa(state):
    # Enumerate all object IDs, then fetch bounded batches and verify no IDs lost.
    """Retrieve all enumerated state HPSA features without truncation."""
    where = HRSA_FIELDS.STATE + " = '" + get_state_name(state) + "'"
    response = requests.get(
        HRSA_PRIMARY_CARE_HPSA_URL,
        params={'where': where, 'returnIdsOnly': 'true', 'f': 'json'},
        timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    if 'error' in payload or 'objectIds' not in payload:
        raise ValueError('HRSA object-ID enumeration unavailable.')
    ids = payload['objectIds'] or []
    field = payload.get('objectIdFieldName')
    if not field or len(ids) != len(set(ids)):
        raise ValueError('HRSA object-ID enumeration malformed.')
    records = {}
    for offset in range(0, len(ids), 150):
        parts = []
        for identifier in ids[offset : offset + 150]:
            parts.append(str(identifier))
        response = requests.get(
            HRSA_PRIMARY_CARE_HPSA_URL,
            params={
                'where': where,
                'objectIds': ','.join(parts),
                'outFields': '*',
                'returnGeometry': 'false',
                'f': 'json',
            },
            timeout=45,
        )
        response.raise_for_status()
        data = response.json()
        if 'error' in data or data.get('exceededTransferLimit'):
            raise ValueError('HRSA batch is unavailable or incomplete.')
        for feature in data.get('features', []):
            attributes = feature.get('attributes', {})
            identifier = attributes.get(field)
            if identifier not in ids or str(identifier) in records:
                raise ValueError('HRSA returned unexpected/duplicate object IDs.')
            if attributes.get(HRSA_FIELDS.STATE) != get_state_name(state):
                raise ValueError('HRSA returned out-of-state features.')
            records[str(identifier)] = feature
    if len(records) != len(ids):
        raise ValueError('HRSA enumeration count does not match retrieved features.')
    return records


# Coordinate address checks


def address_matches(point, row):
    """Require cached coordinates to match the current hospital address."""
    for cached_field, source_field in (
        ('address', 'address'),
        ('city', 'citytown'),
        ('state', 'state'),
        ('zip_code', 'zip_code'),
    ):
        if (
            str(point.get(cached_field) or '').strip().upper()
            != str(row.get(source_field) or '').strip().upper()
        ):
            return False
    return True


# Coordinate import and explicit gaps


def fetch_coordinates(state, hospitals):
    # Preserve unavailable coordinates explicitly; never invent replacement points.
    """Reuse verified points and record unavailable matches explicitly."""
    records = {}
    available = 0
    for index, (ccn, row) in enumerate(hospitals.items(), start=1):
        print(f'Coordinates {state} {index}/{len(hospitals)}', flush=True)
        try:
            point = read_coordinate_cache(ccn)
            if point is not None and address_matches(point, row):
                with sqlite3.connect(COORDINATE_DB_PATH) as connection:
                    stamp = connection.execute(
                        'SELECT updated_at FROM hospital_coordinates WHERE facility_id=?', (ccn,)
                    ).fetchone()
                point['coordinate_observed_at'] = stamp[0]
                point['coordinate_origin'] = 'verified_existing_sqlite_cache'
            else:
                coordinates = geocode_address(
                    row.get('address', ''),
                    row.get('citytown', ''),
                    row['state'],
                    row.get('zip_code', ''),
                )
                if coordinates is None:
                    raise ValueError('No Census address match.')
                coordinate_record = {}
                coordinate_record['facility_id'] = ccn
                coordinate_record['facility_name'] = row['facility_name']
                coordinate_record['address'] = row.get('address')
                coordinate_record['city'] = row.get('citytown')
                coordinate_record['state'] = state
                coordinate_record['zip_code'] = row.get('zip_code')
                for copied_key, copied_value in (coordinates).items():
                    coordinate_record[copied_key] = copied_value
                coordinate_record['coordinate_observed_at'] = datetime.now(timezone.utc).isoformat()
                coordinate_record['coordinate_origin'] = 'census_geocoder'

                point = coordinate_record
                write_coordinate_cache(point)
            if not math.isfinite(point['latitude']) or not math.isfinite(point['longitude']):
                raise ValueError('Non-finite coordinates.')
            if not -90 <= point['latitude'] <= 90 or not -180 <= point['longitude'] <= 180:
                raise ValueError('Coordinates out of range.')
            coordinate_status = {}
            coordinate_status['available'] = True
            for copied_key, copied_value in (point).items():
                coordinate_status[copied_key] = copied_value

            records[ccn] = coordinate_status
            available += 1
        except (requests.RequestException, ValueError, sqlite3.Error) as error:
            records[ccn] = {
                'facility_id': ccn,
                'available': False,
                'error_code': type(error).__name__,
                'reason': 'No verified coordinates available; excluded from distance ranking.',
            }
    return records, available


# Independent component refresh


def import_reference_data(states, init_db=False, skip_coordinates=False):
    """Refresh each reference component independently for selected states."""
    if init_db:
        store.initialize_schema()
    results = []
    # A failed component must not erase another component's valid snapshot.
    for value in states:
        state = normalize_state(value)
        try:
            hospitals, result = import_directory(state)
            results.append(result)
            print(json.dumps(result), flush=True)
        except Exception as error:
            result = {
                'kind': 'hospital_directory',
                'state': state,
                'status': 'failed',
                'error_code': type(error).__name__,
            }
            results.append(result)
            print(json.dumps(result), flush=True)
            hospitals = None
        for kind, fetch, url, year in (
            ('county_demographics', fetch_demographics, CENSUS_API_URL, 2024),
            ('primary_care_hpsa', fetch_hpsa, HRSA_PRIMARY_CARE_HPSA_URL, None),
        ):
            try:
                records = fetch(state)
                result = store.publish(
                    kind, state, records, url, datetime.now(timezone.utc), source_year=year
                )
            except Exception as error:
                result = {
                    'kind': kind,
                    'state': state,
                    'status': 'failed',
                    'error_code': type(error).__name__,
                }
            results.append(result)
            print(json.dumps(result), flush=True)
        if hospitals is not None and not skip_coordinates:
            records, available = fetch_coordinates(state, hospitals)
            result = store.publish(
                'hospital_coordinates',
                state,
                records,
                CENSUS_GEOCODER_URL,
                datetime.now(timezone.utc),
                available_count=available,
                metadata={
                    'candidate_count': len(hospitals),
                    'unavailable_count': len(hospitals) - available,
                },
            )
            results.append(result)
            print(json.dumps(result), flush=True)
    return results
