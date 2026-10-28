"""Explicit CMS bulk ingestion; state snapshots publish only after a full CSV scan."""

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import uuid
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.services import financial_store as store
from app.utils.state_utils import normalize_state

CATALOG_URL = 'https://data.cms.gov/data.json'
CACHE_DIR = store.ROOT / 'data/imports'
TITLE_PATTERN = re.compile(r'^Hospital Provider Cost Report : (\d{4})-')
ID_PATTERN = re.compile(r'/dataset/([a-f0-9-]{36})/')
MAX_DOWNLOAD_BYTES = 250 * 1024 * 1024


# Official source discovery


def discover_sources(catalog):
    """Require current catalog metadata; never import using guessed fallback URLs."""
    sources = {}
    for entry in catalog.get('dataset', []):
        match = TITLE_PATTERN.match(entry.get('title', ''))
        if not match:
            continue
        year = int(match.group(1))
        identifier = ID_PATTERN.search(entry.get('identifier') or entry.get('@id', ''))
        if not identifier:
            continue
        for distribution in entry.get('distribution', []):
            url = distribution.get('downloadURL', '')
            if urlparse(url).hostname != 'data.cms.gov' or not url.lower().endswith('.csv'):
                continue
            source = {
                'dataset_id': identifier.group(1),
                'url': url,
                'modified': distribution.get('modified') or entry.get('modified'),
            }
            old = sources.get(year)
            if old is None or str(source['modified'] or '') > str(old['modified'] or ''):
                sources[year] = source
    return sources


# Verified bulk downloads


def download_source(source, session, force=False):
    """Resume at file/year boundaries; truncated downloads never replace a valid cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    identity = json.dumps(source, sort_keys=True).encode()
    key = hashlib.sha256(identity).hexdigest()
    path = CACHE_DIR / (key + '.csv')
    meta_path = CACHE_DIR / (key + '.json')
    if not force and path.exists() and meta_path.exists():
        metadata = json.loads(meta_path.read_text(encoding='utf-8'))
        if hashlib.sha256(path.read_bytes()).hexdigest() == metadata['sha256']:
            return path, metadata
    temporary = path.with_suffix('.part')
    digest = hashlib.sha256()
    downloaded = 0
    with session.get(
        source['url'], timeout=(15, 90), stream=True, headers={'Accept-Encoding': 'identity'}
    ) as response:
        response.raise_for_status()
        if urlparse(response.url).hostname != 'data.cms.gov':
            raise ValueError('Unexpected source redirect.')
        with temporary.open('wb') as output:
            for chunk in response.iter_content(1024 * 128):
                downloaded += len(chunk)
                if downloaded > MAX_DOWNLOAD_BYTES:
                    raise ValueError('Download exceeds the configured size bound.')
                digest.update(chunk)
                output.write(chunk)
        expected_length = response.headers.get('Content-Length')
        if expected_length and not response.headers.get('Content-Encoding'):
            if downloaded != int(expected_length):
                raise ValueError('Download content length mismatch.')
    if not downloaded:
        raise ValueError('Empty source download.')
    metadata = {
        'sha256': digest.hexdigest(),
        'bytes': downloaded,
        'retrieved_at': datetime.now(timezone.utc).isoformat(),
    }
    temporary.replace(path)
    meta_path.write_text(json.dumps(metadata), encoding='utf-8')
    return path, metadata


# CSV validation and state selection


def scan_state_rows(path, state):
    """Preserve all raw source fields/rows; inventory all CCNs before filtering state."""
    required = {
        'Provider CCN',
        'State Code',
        'Hospital Name',
        'Fiscal Year Begin Date',
        'Fiscal Year End Date',
    }
    selected = []
    inventory = {}
    count = 0
    with Path(path).open('r', encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('CMS CSV is missing required source columns.')
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError('CMS CSV has duplicate column names.')
        for number, row in enumerate(reader, start=1):
            if None in row or None in row.values():
                raise ValueError('Incomplete or malformed source CSV row.')
            ccn = row['Provider CCN'].strip()
            row_state = row['State Code'].strip().upper()
            if not re.fullmatch(r'[0-9A-Za-z]{6}', ccn):
                raise ValueError('Source row has a missing or invalid CCN.')
            if not re.fullmatch(r'[A-Z]{2}', row_state):
                raise ValueError('Source row has an invalid state code.')
            count += 1
            if ccn not in inventory:
                inventory[ccn] = []
            if row_state not in inventory[ccn]:
                inventory[ccn].append(row_state)
            if row_state == state:
                selected.append((number, row))
    if not count:
        raise ValueError('Source CSV contains no data rows.')
    return selected, inventory, count


# Version comparison


def source_changed(active, source):
    """Compare the imported source version with current catalog metadata."""
    if active is None:
        return True
    return (active[0], active[1], active[2]) != (
        source['dataset_id'],
        source['url'],
        source.get('modified'),
    )


# One-year import transaction


def import_year(state, year, source, session, refresh=False):
    """A retry starts a new audited run; previous complete data stays active on failure."""
    active = store.active_import(state, year)
    if not refresh and not source_changed(active, source):
        return {'state': state, 'year': year, 'status': 'unchanged', 'row_count': active[4]}
    run_id = uuid.uuid4()
    store.start_import(run_id, state, year, source)
    try:
        path, metadata = download_source(source, session, force=refresh)
        selected, inventory, count = scan_state_rows(path, state)
        store.complete_import(
            run_id,
            state,
            year,
            selected,
            inventory,
            count,
            metadata['sha256'],
            metadata['retrieved_at'],
        )
        return {
            'state': state,
            'year': year,
            'status': 'complete',
            'row_count': len(selected),
            'national_row_count': count,
            'download_bytes': metadata['bytes'],
        }
    except Exception as error:
        # Store exception type only: driver exceptions can contain sensitive details.
        store.fail_import(run_id, type(error).__name__)
        return {
            'state': state,
            'year': year,
            'status': 'failed',
            'error_code': type(error).__name__,
        }


# Multi-year import workflow


def run_import(
    state, start_year=None, end_year=None, init_db=False, check_only=False, refresh=False
):
    """No scheduled behavior: invoke this job independently of user analysis requests."""
    # Validate the requested scope and initialize only when explicitly requested.
    state = normalize_state(state)
    if init_db:
        store.initialize_schema()
    retry = Retry(total=3, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504))
    with requests.Session() as session:
        session.mount('https://', HTTPAdapter(max_retries=retry))
        # Discover the current catalog before choosing source years.
        response = session.get(CATALOG_URL, timeout=(15, 90))
        response.raise_for_status()
        sources = discover_sources(response.json())
        if not sources:
            raise ValueError('No current CMS CSV sources discovered.')
        if end_year is None:
            end_year = max(sources)
        if start_year is None:
            start_year = min(sources)
        if start_year < 2011 or start_year > end_year:
            raise ValueError('Invalid source year interval.')
        # Check or import each year independently and report its outcome.
        results = []
        for year in range(start_year, end_year + 1):
            source = sources.get(year)
            if source is None:
                result = {'state': state, 'year': year, 'status': 'source_not_published'}
            elif check_only:
                changed = source_changed(store.active_import(state, year), source)
                status = 'unchanged'
                if changed:
                    status = 'update_available'
                result = {'state': state, 'year': year, 'status': status}
            else:
                print(f'Importing {state} {year}…', flush=True)
                result = import_year(state, year, source, session, refresh)
            results.append(result)
            print(json.dumps(result), flush=True)
        return results
