"""Offline reference-snapshot routing and import-completeness regression checks."""
from unittest.mock import Mock

import pytest

from app.services import reference_store as store
from app.services import reference_import_service as importer
from app.services import cms_service, census_service, hrsa_service, geocoding_service


def hospital():
    return {'facility_id': '520109', 'facility_name': 'Mile Bluff', 'state': 'WI',
            'address': '100 MAIN ST', 'citytown': 'Mauston', 'zip_code': '53948',
            'countyparish': 'Juneau', 'hospital_type': 'Acute Care Hospitals'}


def snapshot(records):
    return {'records': records, 'data_provenance': {'storage': 'postgresql_snapshot',
            'source_retrieved_at': '2026-10-27T00:00:00+00:00', 'status': 'complete'}}


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setenv('REFERENCE_DATA_MODE', 'database_only')
    network = Mock(side_effect=AssertionError('External HTTP must not be used'))
    monkeypatch.setattr('requests.get', network)
    cms_service.HOSPITAL_ID_CACHE.clear()
    return network


def test_state_directory_and_name_lookup_use_stored_records(offline, monkeypatch):
    monkeypatch.setattr(store, 'state_snapshot', lambda *args: snapshot({'520109': hospital()}))
    rows = cms_service.get_hospitals_by_state('Wisconsin')
    assert len(rows) == 1
    matches = cms_service.search_hospitals_by_name('Mile Bluff', 'WI', 'Juneau County')
    assert matches[0].source_provenance['storage'] == 'postgresql_snapshot'
    offline.assert_not_called()


def test_uncovered_state_does_not_become_zero_hospitals(offline, monkeypatch):
    monkeypatch.setattr(store, 'state_snapshot', lambda *args: None)
    with pytest.raises(store.ReferenceDataUnavailable, match='not been imported'):
        cms_service.get_hospitals_by_state('CA')


def test_name_without_state_does_not_claim_unique_national_match(offline):
    with pytest.raises(ValueError, match='Provide a state'):
        cms_service.search_hospitals_by_name('Mile Bluff')


def test_ccn_lookup_uses_stored_directory_and_cache(offline, monkeypatch):
    lookup = Mock(return_value={**hospital(), 'source_provenance': {'storage': 'postgresql_snapshot'}})
    monkeypatch.setattr(store, 'hospital_by_id', lookup)
    assert cms_service.get_hospital_by_id('520109').facility_name == 'Mile Bluff'
    assert cms_service.get_hospital_by_id('520109').facility_name == 'Mile Bluff'
    lookup.assert_called_once()


def test_county_snapshot_works_without_census_key(offline, monkeypatch):
    monkeypatch.setattr(census_service, 'CENSUS_API_KEY', None)
    raw = {'county': 'JUNEAU', 'total_population': 100, '_raw_record': {'NAME': 'Juneau County'}}
    monkeypatch.setattr(store, 'state_snapshot', lambda *args: snapshot({'juneau': raw}))
    result = census_service.get_county_demographics('55', 'Juneau County')
    assert result['total_population'] == 100
    assert '_raw_record' not in result
    assert result['data_provenance']['storage'] == 'postgresql_snapshot'
    assert census_service.get_county_demographics('55', 'Unknown') is None


def test_hpsa_snapshot_preserves_population_type_and_inactive_status(offline, monkeypatch):
    fields = hrsa_service.HRSA_FIELDS
    features = {}
    for key, status in (('1', 'Designated'), ('2', 'Withdrawn')):
        features[key] = {'attributes': {fields.COUNTY: 'Juneau', fields.STATE: 'Wisconsin',
            fields.HPSA_SOURCE_ID: key, fields.HPSA_STATUS: status, fields.HPSA_SCORE: 15,
            fields.HPSA_TYPE: 'Population', fields.HPSA_POPULATION_TYPE: 'Low Income'}}
    monkeypatch.setattr(store, 'state_snapshot', lambda *args: snapshot(features))
    result = hrsa_service.get_county_primary_care_hpsa('WI', 'Juneau County')
    assert result['designation_count'] == 2
    assert result['active_designation_count'] == 1
    assert result['designations'][0]['population_type'] == 'Low Income'
    assert result['data_provenance']['storage'] == 'postgresql_snapshot'


def test_complete_empty_hpsa_snapshot_is_distinct_from_unavailable(offline, monkeypatch):
    monkeypatch.setattr(store, 'state_snapshot', lambda *args: snapshot({}))
    assert hrsa_service.get_county_primary_care_hpsa('WI', 'Juneau')['active_designation_count'] == 0
    monkeypatch.setattr(store, 'state_snapshot', lambda *args: None)
    with pytest.raises(store.ReferenceDataUnavailable):
        hrsa_service.get_county_primary_care_hpsa('WY', 'Fremont')


def test_unavailable_coordinate_snapshot_never_regeocodes(offline, monkeypatch):
    monkeypatch.setattr(store, 'state_snapshot', lambda *args: snapshot({'520109': {'available': False}}))
    assert geocoding_service.geocode_hospital_record(hospital()) is None
    offline.assert_not_called()


def test_coordinate_snapshot_rejects_changed_addresses(offline, monkeypatch):
    raw = {'available': True, 'address': 'OLD ADDRESS', 'city': 'Mauston', 'state': 'WI',
           'zip_code': '53948', 'latitude': 43.8, 'longitude': -90}
    monkeypatch.setattr(store, 'state_snapshot', lambda *args: snapshot({'520109': raw}))
    assert geocoding_service.geocode_hospital_record(hospital()) is None
    raw['address'] = '100 MAIN ST'
    assert geocoding_service.geocode_hospital_record(hospital())['latitude'] == 43.8


def test_hybrid_mode_can_explicitly_fallback(monkeypatch):
    monkeypatch.setenv('REFERENCE_DATA_MODE', 'hybrid')
    monkeypatch.setattr(store, 'state_snapshot', lambda *args: None)
    cms_service.STATE_HOSPITAL_CACHE.clear()
    live = Mock(return_value=[hospital()])
    monkeypatch.setattr(cms_service, '_query_hospital_rows', live)
    assert len(cms_service.get_hospitals_by_state('WI')) == 1
    live.assert_called_once()
    cms_service.STATE_HOSPITAL_CACHE.clear()


def test_missing_hrsa_object_is_not_a_complete_snapshot(monkeypatch):
    ids = Mock()
    ids.json.return_value = {'objectIds': [1, 2], 'objectIdFieldName': 'OBJECTID'}
    batch = Mock()
    batch.json.return_value = {'features': [{'attributes': {'OBJECTID': 1, 'STATE_NM': 'Wisconsin'}}]}
    monkeypatch.setattr('requests.get', Mock(side_effect=[ids, batch]))
    with pytest.raises(ValueError, match='count does not match'):
        importer.fetch_hpsa('WI')


def test_coordinate_import_records_failures_without_guessing(monkeypatch):
    monkeypatch.setattr(importer, 'read_coordinate_cache', lambda *args: None)
    monkeypatch.setattr(importer, 'geocode_address', lambda *args: None)
    records, available = importer.fetch_coordinates('WI', {'520109': hospital()})
    assert available == 0
    assert records['520109']['available'] is False
    assert 'latitude' not in records['520109']


def test_non_coordinate_components_cannot_publish_partial_results():
    with pytest.raises(ValueError, match='Only coordinate'):
        store.publish('county_demographics', 'WI', {'a': {}}, 'https://api.census.gov', None,
                      available_count=0)


def test_database_failure_is_not_silently_fetched_in_database_mode(offline, monkeypatch):
    def fail(*args):
        raise store.ReferenceDataUnavailable('Database unavailable')
    monkeypatch.setattr(store, 'state_snapshot', fail)
    with pytest.raises(store.ReferenceDataUnavailable):
        census_service.get_county_demographics('55', 'Juneau')
