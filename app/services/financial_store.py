"""Private PostgreSQL snapshots; no CMS requests or database writes during analysis."""

import json
import logging
import os
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv
import psycopg
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool, PoolTimeout

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / '.env')
logger = logging.getLogger(__name__)
_pool = None
_pool_lock = Lock()


class FinancialStoreUnavailable(Exception):
    """Sanitized storage failure; never include the database URL in public output."""


# Storage mode and database connections


def data_mode():
    """Configured databases default to offline analysis; live mode remains compatible."""
    default = 'live'
    if os.getenv('DATABASE_URL'):
        default = 'database_only'
    mode = os.getenv('FINANCIAL_DATA_MODE', default)
    if mode not in ('live', 'hybrid', 'database_only'):
        raise FinancialStoreUnavailable('Invalid FINANCIAL_DATA_MODE.')
    return mode


def connect():
    """Use TLS and finite connection/statement waits, including session poolers."""
    url = os.getenv('DATABASE_URL')
    if not url:
        raise FinancialStoreUnavailable('DATABASE_URL is not configured.')
    return psycopg.connect(url, sslmode='require', connect_timeout=8, prepare_threshold=None)


def read_pool():
    """Reuse at most four TLS connections across parallel year lookups."""
    global _pool
    with _pool_lock:
        if _pool is None:
            url = os.getenv('DATABASE_URL')
            if not url:
                raise FinancialStoreUnavailable('DATABASE_URL is not configured.')
            _pool = ConnectionPool(
                url,
                min_size=0,
                max_size=4,
                timeout=10,
                max_idle=60,
                open=True,
                kwargs={'sslmode': 'require', 'connect_timeout': 8, 'prepare_threshold': None},
            )
    return _pool


# Read-only snapshot queries


def _read(statement, parameters=()):
    """Enforce transaction-level read-only behavior, not just connection options."""
    try:
        with read_pool().connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION READ ONLY')
                cursor.execute("SET LOCAL statement_timeout = '15s'")
                cursor.execute(statement, parameters)
                return cursor.fetchall()
    except (psycopg.Error, OSError, PoolTimeout):
        raise FinancialStoreUnavailable('Financial snapshot database is unavailable.') from None


def available_years():
    """Completed imported years only, never an attempted or failed import."""
    rows = _read('''SELECT DISTINCT c.dataset_year FROM hospital_data.financial_coverage c
        JOIN hospital_data.financial_import_runs i ON i.id=c.active_run_id
        AND i.state=c.state AND i.dataset_year=c.dataset_year
        WHERE i.status='complete' ORDER BY c.dataset_year''')
    result = []
    for row in rows:
        result.append(row[0])
    return result


def lookup_rows(facility_id, year):
    """None means not covered; [] means proven absent from a fully scanned source."""
    rows = _read(
        '''
        SELECT r.raw_record, i.dataset_id, i.source_url, i.source_sha256,
               i.source_retrieved_at, i.finished_at, i.state, i.id::text
        FROM hospital_data.financial_report_rows r
        JOIN hospital_data.financial_import_runs i ON i.id = r.run_id
        JOIN hospital_data.financial_coverage c ON c.active_run_id = i.id
        AND c.state = i.state AND c.dataset_year = i.dataset_year
        WHERE r.facility_id = %s AND c.dataset_year = %s AND i.status = 'complete'
        ORDER BY i.finished_at DESC, r.source_row_number
    ''',
        (facility_id, year),
    )
    result = []
    selected_run = None
    for raw, dataset_id, url, digest, retrieved, imported, state, run_id in rows:
        if selected_run is None:
            selected_run = run_id
        if run_id != selected_run:
            continue
        provenance = {
            'storage': 'postgresql_snapshot',
            'dataset_id': dataset_id,
            'dataset_year': year,
            'imported_state': state,
            'source_url': url,
            'source_sha256': digest,
            'source_retrieved_at': retrieved.isoformat(),
            'imported_at': imported.isoformat(),
            'note': 'Stored source snapshot; not a live CMS freshness check.',
        }
        stored_record = {}
        for copied_key, copied_value in (raw).items():
            stored_record[copied_key] = copied_value
        stored_record['_source_provenance'] = provenance

        result.append(stored_record)
    if result:
        return result
    # The full CSV inventory prevents a state-only import from falsely declaring
    # an out-of-state/moved hospital absent. Only national nonexistence is empty.
    inventories = _read(
        '''
        SELECT national_inventory ? %s
        FROM hospital_data.financial_import_runs
        WHERE dataset_year = %s AND status = 'complete' AND national_inventory IS NOT NULL
        ORDER BY finished_at DESC LIMIT 1
    ''',
        (facility_id, year),
    )
    if inventories and inventories[0][0] is False:
        return []
    return None


# Explicit schema and import operations


def initialize_schema():
    """Explicit administrative operation; never run automatically on user queries."""
    sql = (ROOT / 'supabase/migrations/202610270001_financial_snapshots.sql').read_text(
        encoding='utf-8'
    )
    with connect() as connection:
        connection.execute(sql)
        guard = ROOT / 'supabase/migrations/202610270003_snapshot_scope_constraints.sql'
        connection.execute(guard.read_text(encoding='utf-8'))


def active_import(state, year):
    """Read the active complete snapshot for one state and year."""
    rows = _read(
        '''
        SELECT i.dataset_id, i.source_url, i.catalog_modified, i.source_sha256,
               i.state_row_count, i.id::text
        FROM hospital_data.financial_import_runs i
        JOIN hospital_data.financial_coverage c ON c.active_run_id = i.id
        AND c.state = i.state AND c.dataset_year = i.dataset_year
        WHERE c.state = %s AND c.dataset_year = %s AND i.status = 'complete'
    ''',
        (state, year),
    )
    if rows:
        return rows[0]
    return None


def start_import(run_id, state, year, source):
    """Record an import attempt before downloading or writing report rows."""
    with connect() as connection:
        connection.execute(
            '''INSERT INTO hospital_data.financial_import_runs
            (id, state, dataset_year, dataset_id, source_url, catalog_modified, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'running')''',
            (run_id, state, year, source['dataset_id'], source['url'], source.get('modified')),
        )


def fail_import(run_id, error_code):
    """Keep failure diagnostics without changing the previous complete snapshot."""
    with connect() as connection:
        connection.execute(
            '''UPDATE hospital_data.financial_import_runs
            SET status = 'failed', finished_at = now(), error_code = %s
            WHERE id = %s AND status = 'running' ''',
            (error_code, run_id),
        )


# Atomic snapshot publication


def complete_import(run_id, state, year, selected, inventory, row_count, digest, retrieved):
    """Rows, completion marker and active pointer commit atomically or all roll back."""
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '120s'")
            cursor.execute(
                '''SELECT pg_advisory_xact_lock(hashtext(%s))''',
                ('hospital-financial:' + state + ':' + str(year),),
            )
            # Preserve every source report in the same transaction.
            with cursor.copy(
                'COPY hospital_data.financial_report_rows (run_id, source_row_number, facility_id, fiscal_year_begin, fiscal_year_end, raw_record) FROM STDIN'
            ) as copy:
                for number, raw in selected:
                    copy.write_row(
                        (
                            str(run_id),
                            number,
                            raw['Provider CCN'],
                            raw.get('Fiscal Year Begin Date'),
                            raw.get('Fiscal Year End Date'),
                            json.dumps(raw),
                        )
                    )
            # Verify stored rows before marking the snapshot complete.
            cursor.execute(
                'SELECT count(*) FROM hospital_data.financial_report_rows WHERE run_id = %s',
                (run_id,),
            )
            if cursor.fetchone()[0] != len(selected):
                raise ValueError('Imported row count mismatch.')
            cursor.execute(
                '''UPDATE hospital_data.financial_import_runs SET
                status = 'complete', finished_at = now(), national_row_count = %s,
                state_row_count = %s, source_sha256 = %s, source_retrieved_at = %s,
                national_inventory = %s WHERE id = %s AND status = 'running' ''',
                (row_count, len(selected), digest, retrieved, Jsonb(inventory), run_id),
            )
            if cursor.rowcount != 1:
                raise ValueError('Import run is no longer running.')
            # Activate this complete state/year version atomically.
            cursor.execute(
                '''INSERT INTO hospital_data.financial_coverage
                (state, dataset_year, active_run_id) VALUES (%s, %s, %s)
                ON CONFLICT (state, dataset_year) DO UPDATE SET active_run_id = EXCLUDED.active_run_id''',
                (state, year, run_id),
            )
