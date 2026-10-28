"""Search a dated CMS/IHS reference directory, not a live hospital registry."""

from contextlib import closing
from pathlib import Path
from threading import Lock
import hashlib
import json
import re
import sqlite3
import unicodedata

from app.utils.state_utils import normalize_state

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TRIBAL_DIRECTORY_DB_PATH = PROJECT_ROOT / 'data' / 'tribal_facilities.db'
TRIBAL_DIRECTORY_SEED_PATH = PROJECT_ROOT / 'data' / 'reference' / 'ihs_cms_tribal_2020.json'
_DIRECTORY_LOCK = Lock()


def _normalize_text(value):
    """Match words without inventing aliases or dropping supplied constraints."""
    characters = []
    for character in unicodedata.normalize('NFKD', value):
        if not unicodedata.combining(character):
            characters.append(character)
    value = ''.join(characters).casefold()
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', value).split())


def initialize_tribal_directory():
    """Build the local search cache from a versioned, reviewable JSON snapshot."""
    # 1. Fingerprint the curated source so new snapshots replace old indexes.
    seed_bytes = TRIBAL_DIRECTORY_SEED_PATH.read_bytes()
    fingerprint = hashlib.sha256(seed_bytes).hexdigest()
    document = json.loads(seed_bytes)
    if document['record_count'] != len(document['records']):
        raise ValueError('Historical directory snapshot record count is inconsistent.')

    # 2. Keep import and metadata updates atomic; a failed import is rolled back.
    with _DIRECTORY_LOCK:
        TRIBAL_DIRECTORY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(TRIBAL_DIRECTORY_DB_PATH, timeout=10)) as connection:
            with connection:
                connection.execute('''CREATE TABLE IF NOT EXISTS directory_metadata (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                )''')
                connection.execute('''CREATE TABLE IF NOT EXISTS tribal_facilities (
                    record_id TEXT PRIMARY KEY,
                    facility_name TEXT NOT NULL,
                    facility_type TEXT NOT NULL,
                    ccns_json TEXT NOT NULL,
                    city TEXT NOT NULL,
                    state TEXT NOT NULL,
                    source_page INTEGER NOT NULL,
                    normalized_name TEXT NOT NULL,
                    normalized_city TEXT NOT NULL,
                    normalized_type TEXT NOT NULL
                )''')
                connection.execute(
                    'CREATE INDEX IF NOT EXISTS tribal_facilities_state ON tribal_facilities(state)'
                )
                old = connection.execute(
                    "SELECT value FROM directory_metadata WHERE key = 'seed_sha256'"
                ).fetchone()
                if old is not None and old[0] == fingerprint:
                    return document

                # 3. Preserve one source row and its full list of CCNs, including zeros.
                connection.execute('DELETE FROM tribal_facilities')
                for record in document['records']:
                    connection.execute(
                        '''INSERT INTO tribal_facilities VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )''',
                        (
                            record['record_id'],
                            record['facility_name'],
                            record['facility_type'],
                            json.dumps(record['ccns']),
                            record['city'],
                            record['state'],
                            record['source_page'],
                            _normalize_text(record['facility_name']),
                            _normalize_text(record['city']),
                            _normalize_text(record['facility_type']),
                        ),
                    )
                connection.execute(
                    '''INSERT INTO directory_metadata(key, value)
                    VALUES ('seed_sha256', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value''',
                    (fingerprint,),
                )
    return document


def search_tribal_facilities(name=None, state=None, city=None, facility_type=None, limit=20):
    """Search the 2020 historical snapshot with explicit filters and provenance."""
    # 1. Validate filters before opening the database; no unfiltered full dump.
    if not any((name, state, city, facility_type)):
        return {'error': 'Provide a name, state, city, or facility type.'}
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
        return {'error': 'limit must be an integer between 1 and 50.'}
    conditions = []
    parameters = []
    try:
        for field, value in (
            ('normalized_name', name),
            ('normalized_city', city),
            ('normalized_type', facility_type),
        ):
            if value is None:
                continue
            if not isinstance(value, str):
                raise ValueError('Directory filters must be text.')
            normalized = _normalize_text(value)
            if not normalized:
                raise ValueError('Directory filters must not be blank.')
            for token in normalized.split():
                conditions.append("(' ' || " + field + " || ' ') LIKE ?")
                parameters.append('% ' + token + ' %')
        if state is not None:
            conditions.append('state = ?')
            parameters.append(normalize_state(state))
    except (ValueError, AttributeError) as error:
        return {'error': str(error)}

    # 2. Query a local structured index, retaining total and returned counts.
    document = initialize_tribal_directory()
    where = ' AND '.join(conditions)
    with closing(sqlite3.connect(TRIBAL_DIRECTORY_DB_PATH, timeout=10)) as connection:
        connection.row_factory = sqlite3.Row
        total = connection.execute(
            'SELECT COUNT(*) FROM tribal_facilities WHERE ' + where, parameters
        ).fetchone()[0]
        rows = connection.execute(
            'SELECT * FROM tribal_facilities WHERE '
            + where
            + ' ORDER BY facility_name, state, record_id LIMIT ?',
            parameters + [limit],
        ).fetchall()

    # 3. Expose listed identifiers as historical data, never as an active target CCN.
    facilities = []
    for row in rows:
        facilities.append(
            {
                'record_id': row['record_id'],
                'facility_name': row['facility_name'],
                'facility_type': row['facility_type'],
                'listed_ccns': json.loads(row['ccns_json']),
                'city': row['city'],
                'state': row['state'],
                'listed_as_hospital': row['facility_type'] == 'Hospital',
                'current_status_verified': False,
                'source_page': row['source_page'],
                'citation_url': document['source_url'] + '#page=' + str(row['source_page']),
            }
        )
    return {
        'directory_kind': 'historical_tribal_facilities',
        'filters': {'name': name, 'state': state, 'city': city, 'facility_type': facility_type},
        'count': total,
        'returned_count': len(facilities),
        'truncated': total > len(facilities),
        'facilities': facilities,
        'source': document['source_title'],
        'source_url': document['source_url'],
        'source_created_date': document['source_created_date'],
        'historical_snapshot': True,
        'limitations': [
            'This is a 2020 historical listing, not confirmation of current operation, name, certification or tribal affiliation.',
            'A listed CCN may identify a clinic, dialysis center or another facility type, not a hospital.',
            'Do not send non-hospital listed CCNs to hospital financial, investigation or comparison tools.',
            'Even entries listed as hospitals require current CMS identity/type confirmation before hospital-specific analysis.',
            'The source has no county, street address, coordinates, service capacity or financial explanation.',
            'No match in this snapshot does not establish that an institution does not exist.',
        ],
    }
