"""Offline database-first contracts; these tests never access the real database."""
import csv
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from app.services import cost_report_service as reports
from app.services import financial_store as store
from app.services import financial_import_service as ingestion


def row(ccn='520109', state='WI'):
    return {'Provider CCN': ccn, 'State Code': state, 'Hospital Name': 'Example',
            'Fiscal Year Begin Date': '2024-01-01', 'Fiscal Year End Date': '2024-12-31'}


def test_stored_rows_bypass_catalog_and_http(monkeypatch):
    monkeypatch.setenv('FINANCIAL_DATA_MODE', 'database_only')
    monkeypatch.setattr(store, 'lookup_rows', lambda ccn, year: [row()])
    catalog = Mock(side_effect=AssertionError('Catalog must not be used'))
    monkeypatch.setattr(reports, 'get_cost_report_datasets', catalog)
    assert reports.fetch_cost_report_rows('520109', 2024) == [row()]
    catalog.assert_not_called()


def test_database_only_missing_coverage_is_unavailable_not_no_filing(monkeypatch):
    monkeypatch.setenv('FINANCIAL_DATA_MODE', 'database_only')
    monkeypatch.setattr(store, 'lookup_rows', lambda *args: None)
    with pytest.raises(reports.CostReportUnavailableError, match='not covered'):
        reports.fetch_cost_report_rows('510002', 2024)


def test_complete_national_absence_is_empty_without_network(monkeypatch):
    monkeypatch.setenv('FINANCIAL_DATA_MODE', 'database_only')
    monkeypatch.setattr(store, 'lookup_rows', lambda *args: [])
    assert reports.fetch_cost_report_rows('000000', 2024) == []


def test_database_outage_never_becomes_empty_result(monkeypatch):
    monkeypatch.setenv('FINANCIAL_DATA_MODE', 'database_only')
    def fail(*args):
        raise store.FinancialStoreUnavailable('private detail')
    monkeypatch.setattr(store, 'lookup_rows', fail)
    with pytest.raises(reports.CostReportUnavailableError, match='database unavailable'):
        reports.fetch_cost_report_rows('520109', 2024)


def test_offline_year_discovery_does_not_fetch_cms(monkeypatch):
    monkeypatch.setenv('FINANCIAL_DATA_MODE', 'database_only')
    monkeypatch.setattr(store, 'available_years', lambda: [2020, 2021, 2022, 2023, 2024])
    monkeypatch.setattr(reports, 'get_cost_report_datasets', Mock(side_effect=AssertionError('No CMS')))
    assert reports.get_latest_report_year() == 2024


def test_hybrid_mode_uses_live_fallback_only_for_uncovered_data(monkeypatch):
    monkeypatch.setenv('FINANCIAL_DATA_MODE', 'hybrid')
    monkeypatch.setattr(store, 'lookup_rows', lambda *args: None)
    monkeypatch.setattr(reports, 'get_cost_report_datasets', lambda **kwargs: {2024: 'test-dataset'})
    response = Mock(status_code=200)
    response.json.return_value = [row()]
    remote = Mock(return_value=response)
    monkeypatch.setattr(reports, '_request_rows', remote)
    reports._rows_cache.clear()
    assert reports.fetch_cost_report_rows('520109', 2024) == [row()]
    remote.assert_called_once()
    reports._rows_cache.clear()


def test_live_mode_never_queries_database(monkeypatch):
    monkeypatch.setenv('FINANCIAL_DATA_MODE', 'live')
    monkeypatch.setattr(store, 'lookup_rows', Mock(side_effect=AssertionError('No database')))
    monkeypatch.setattr(reports, 'get_cost_report_datasets', lambda **kwargs: {2024: 'live-test'})
    response = Mock(status_code=200)
    response.json.return_value = []
    monkeypatch.setattr(reports, '_request_rows', lambda *args: response)
    reports._rows_cache.clear()
    assert reports.fetch_cost_report_rows('520109', 2024) == []
    reports._rows_cache.clear()


def test_snapshot_retains_source_provenance_during_parsing():
    value = row()
    value['_source_provenance'] = {'storage': 'postgresql_snapshot', 'source_sha256': 'verified'}
    record = reports.parse_cost_report_row(value, 2024)
    assert record.source_provenance['storage'] == 'postgresql_snapshot'


def test_lookup_empty_requires_national_inventory_confirmation(monkeypatch):
    for inventory, expected in (([], None), ([(True,)], None), ([(False,)], [])):
        mocked = Mock(side_effect=[[], inventory])
        monkeypatch.setattr(store, '_read', mocked)
        assert store.lookup_rows('520109', 2024) == expected


def test_multiple_import_versions_do_not_mix_source_rows(monkeypatch):
    now = datetime.now(timezone.utc)
    values = [(row(), 'dataset', 'https://data.cms.gov/test.csv', 'sha', now, now, 'WI', 'new'),
              (row(), 'old', 'https://data.cms.gov/old.csv', 'oldsha', now, now, 'IL', 'old')]
    monkeypatch.setattr(store, '_read', lambda *args: values)
    result = store.lookup_rows('520109', 2024)
    assert len(result) == 1
    assert result[0]['_source_provenance']['source_sha256'] == 'sha'


def test_csv_scan_preserves_all_rows_and_ccn_leading_zero(tmp_path):
    path = tmp_path / 'sample.csv'
    rows = [row('010001', 'AL'), row(), row()]
    with path.open('w', newline='', encoding='utf-8') as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    selected, inventory, count = ingestion.scan_state_rows(path, 'WI')
    assert count == 3 and len(selected) == 2
    assert inventory['010001'] == ['AL']
    assert selected[0][1] == rows[1]


def test_malformed_csv_is_never_complete(tmp_path):
    path = tmp_path / 'truncated.csv'
    path.write_text('Provider CCN,State Code,Hospital Name,Fiscal Year Begin Date,Fiscal Year End Date\n520109,WI,Example\n')
    with pytest.raises(ValueError, match='Incomplete'):
        ingestion.scan_state_rows(path, 'WI')


def test_update_detection_includes_revisions_not_just_new_years():
    source = {'dataset_id': 'id', 'url': 'https://data.cms.gov/file.csv', 'modified': '2026-10-27'}
    active = ('id', source['url'], source['modified'], 'sha', 10)
    assert not ingestion.source_changed(active, source)
    assert ingestion.source_changed(active, {**source, 'modified': '2026-11-01'})
    assert ingestion.source_changed(None, source)


def test_catalog_does_not_guess_or_accept_unapproved_downloads():
    catalog = {'dataset': [{'title': 'Hospital Provider Cost Report : 2024-01-02',
        'identifier': 'https://data.cms.gov/data-api/v1/dataset/44060663-47d8-4ced-a115-b53b4c270acb/data-viewer',
        'modified': '2026-10-05', 'distribution': [
            {'downloadURL': 'https://untrusted.example/report.csv'},
            {'downloadURL': 'https://data.cms.gov/report.csv'}]}]}
    source = ingestion.discover_sources(catalog)[2024]
    assert source['url'] == 'https://data.cms.gov/report.csv'


def test_unchanged_import_does_not_download_or_write(monkeypatch):
    source = {'dataset_id': 'id', 'url': 'https://data.cms.gov/file.csv', 'modified': 'date'}
    monkeypatch.setattr(store, 'active_import', lambda *args: ('id', source['url'], 'date', 'sha', 144))
    downloader = Mock(side_effect=AssertionError('Must not download'))
    monkeypatch.setattr(ingestion, 'download_source', downloader)
    result = ingestion.import_year('WI', 2020, source, Mock())
    assert result['status'] == 'unchanged'
    downloader.assert_not_called()


def test_failed_download_records_failure_without_publishing_snapshot(monkeypatch):
    monkeypatch.setattr(store, 'active_import', lambda *args: None)
    monkeypatch.setattr(store, 'start_import', Mock())
    failed = Mock()
    publish = Mock()
    monkeypatch.setattr(store, 'fail_import', failed)
    monkeypatch.setattr(store, 'complete_import', publish)
    monkeypatch.setattr(ingestion, 'download_source', Mock(side_effect=ValueError('invalid source')))
    result = ingestion.import_year('WI', 2024, {'dataset_id': 'id'}, Mock())
    assert result['status'] == 'failed'
    failed.assert_called_once()
    publish.assert_not_called()
