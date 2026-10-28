"""Dated state reference snapshots for identity, population, HPSA and coordinates."""

from copy import deepcopy
import hashlib
import json
import os
from threading import Lock
import uuid

from cachetools import TTLCache
from psycopg.types.json import Jsonb
import requests

from app.services import financial_store as store

_cache = TTLCache(maxsize=64, ttl=300)
_cache_lock = Lock()


class ReferenceDataUnavailable(requests.RequestException):
    """Uncovered or failed snapshots are not evidence of zero hospitals/designations."""


# Reference storage policy


def data_mode():
    """Validate the reference-data policy without contacting sources."""
    mode = os.getenv('REFERENCE_DATA_MODE', 'live')
    if mode not in ('live', 'hybrid', 'database_only'):
        raise ReferenceDataUnavailable('Invalid REFERENCE_DATA_MODE.')
    return mode


# Explicit schema setup


def initialize_schema():
    """Apply reference tables and scope constraints explicitly."""
    store.initialize_schema()
    sql = (store.ROOT / 'supabase/migrations/202610270002_reference_snapshots.sql').read_text(
        encoding='utf-8'
    )
    with store.connect() as connection:
        connection.execute(sql)
        guard = store.ROOT / 'supabase/migrations/202610270003_snapshot_scope_constraints.sql'
        connection.execute(guard.read_text(encoding='utf-8'))


def _read(statement, parameters):
    """Read snapshots with sanitized database failure messages."""
    try:
        return store._read(statement, parameters)
    except store.FinancialStoreUnavailable:
        raise ReferenceDataUnavailable('Reference snapshot database unavailable.') from None


# Cached state snapshots


def state_snapshot(kind, state):
    """None is uncovered; an empty records dictionary can be a valid complete result."""
    key = (kind, state)
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None:
            return cached
    rows = _read(
        '''
        SELECT r.record_key, r.payload, i.source_url, i.source_year,
               i.retrieved_at, i.status, i.row_count, i.available_count, i.id::text
        FROM hospital_data.reference_coverage c
        JOIN hospital_data.reference_import_runs i ON i.id = c.active_run_id
        AND i.kind = c.kind AND i.state = c.state
        LEFT JOIN hospital_data.reference_records r ON r.run_id = i.id
        WHERE c.kind = %s AND c.state = %s
    ''',
        (kind, state),
    )
    if not rows:
        return None
    records = {}
    for row in rows:
        if row[0] is not None:
            records[row[0]] = row[1]
    first = rows[0]
    result = {
        'records': records,
        'data_provenance': {
            'storage': 'postgresql_snapshot',
            'source_url': first[2],
            'source_year': first[3],
            'source_retrieved_at': first[4].isoformat(),
            'status': first[5],
            'record_count': first[6],
            'available_count': first[7],
            'snapshot_id': first[8],
            'note': 'Imported snapshot; not a live status check.',
        },
    }
    with _cache_lock:
        _cache[key] = result
    return result


def read_snapshot(kind, state):
    """Apply request-time policy before callers reach any external API."""
    if data_mode() == 'live':
        return None
    try:
        result = state_snapshot(kind, state)
        if result is None and data_mode() == 'database_only':
            raise ReferenceDataUnavailable(
                f'{kind} for {state} has not been imported. Run the reference import job.'
            )
        return result
    except ReferenceDataUnavailable:
        if data_mode() == 'database_only':
            raise
        return None


# CCN lookup within imported states


def hospital_by_id(facility_id):
    """Resolve a CCN only within the imported state directories."""
    rows = _read(
        '''
        SELECT c.state FROM hospital_data.reference_coverage c
        JOIN hospital_data.reference_records r ON r.run_id = c.active_run_id
        WHERE c.kind = 'hospital_directory' AND r.record_key = %s
        ORDER BY c.state LIMIT 1
    ''',
        (facility_id,),
    )
    if rows:
        snapshot = state_snapshot('hospital_directory', rows[0][0])
        raw = deepcopy(snapshot['records'][facility_id])
        raw['source_provenance'] = snapshot['data_provenance']
        return raw
    if data_mode() == 'database_only':
        raise ReferenceDataUnavailable(
            'Hospital CCN is not in the imported state directories; do not infer nonexistence.'
        )
    return None


# Atomic reference publication


def publish(
    kind,
    state,
    records,
    source_url,
    retrieved_at,
    source_year=None,
    available_count=None,
    metadata=None,
):
    """Publish a fully validated component atomically; partial is for coordinates only."""
    if available_count is None:
        available_count = len(records)
    status = 'complete'
    if available_count != len(records):
        if kind != 'hospital_coordinates':
            raise ValueError('Only coordinate snapshots may publish explicit unavailable records.')
        status = 'partial'
    # Hash the validated payload before writing its audit record.
    payload = json.dumps(records, sort_keys=True, ensure_ascii=False, allow_nan=False)
    digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
    run_id = uuid.uuid4()
    with store.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '120s'")
            cursor.execute(
                'SELECT pg_advisory_xact_lock(hashtext(%s))', ('reference:' + kind + ':' + state,)
            )
            cursor.execute(
                '''INSERT INTO hospital_data.reference_import_runs
                (id, kind, state, source_url, source_year, retrieved_at, status,
                 row_count, available_count, payload_sha256, metadata)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (
                    run_id,
                    kind,
                    state,
                    source_url,
                    source_year,
                    retrieved_at,
                    status,
                    len(records),
                    available_count,
                    digest,
                    Jsonb(metadata or {}),
                ),
            )
            # Publish records and their coverage pointer in one transaction.
            with cursor.copy(
                'COPY hospital_data.reference_records (run_id, record_key, payload) FROM STDIN'
            ) as copy:
                for key, value in records.items():
                    copy.write_row(
                        (str(run_id), key, json.dumps(value, ensure_ascii=False, allow_nan=False))
                    )
            cursor.execute(
                'SELECT count(*) FROM hospital_data.reference_records WHERE run_id=%s', (run_id,)
            )
            if cursor.fetchone()[0] != len(records):
                raise ValueError('Reference snapshot row count mismatch.')
            cursor.execute(
                '''INSERT INTO hospital_data.reference_coverage(kind,state,active_run_id)
                VALUES (%s,%s,%s) ON CONFLICT(kind,state)
                DO UPDATE SET active_run_id=EXCLUDED.active_run_id''',
                (kind, state, run_id),
            )
    with _cache_lock:
        _cache.pop((kind, state), None)
    return {
        'kind': kind,
        'state': state,
        'status': status,
        'row_count': len(records),
        'available_count': available_count,
    }
