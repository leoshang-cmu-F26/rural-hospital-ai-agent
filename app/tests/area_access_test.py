"""Offline area access regression tests; no external services or model calls."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from app.services import area_access_service as service
from app.services.chat_context import extract_facility
from app.services.evidence_summary import evidence_summary


def row(ccn, county='Fremont', state='WY'):
    return {'facility_id': ccn, 'facility_name': 'Hospital ' + ccn,
            'countyparish': county, 'citytown': 'Town', 'state': state}


@pytest.fixture
def sources():
    rows = [row('001'), row('002'), row('003', 'Natrona'), row('004', 'Natrona')]
    patches = [
        patch.object(service, 'get_hospitals_by_state', return_value=rows),
        patch.object(service, 'get_latest_report_year', return_value=2024),
        patch.object(service, 'get_financial_data_by_hospital', side_effect=lambda ccn, year: SimpleNamespace(rural_versus_urban={'001': 'R', '002': 'R', '003': 'U', '004': None}[ccn])),
        patch.object(service, 'geocode_hospital_record', side_effect=lambda item: {'latitude': 42 + int(item['facility_id']) / 10, 'longitude': -108}),
        patch.object(service, 'get_hospital_demographics', return_value={'total_population': 100, 'source': 'Census ACS 2024'}),
        patch.object(service, 'get_county_primary_care_hpsa', return_value={'active_designation_count': 1, 'source': 'HRSA'}),
    ]
    mocks = []
    for item in patches:
        mocks.append(item.start())
    yield mocks
    for item in reversed(patches):
        item.stop()


def test_state_coverage_unknown_and_county_dedup(sources):
    result = service.analyze_area_access('Wyoming')
    assert result['coverage']['area_hospital_count'] == 4
    assert result['coverage']['selected_hospital_count'] == 2
    assert result['coverage']['excluded_urban_count'] == 1
    assert result['coverage']['unknown_classification_count'] == 1
    assert len(result['counties']) == 1
    sources[4].assert_called_once_with('001')
    sources[5].assert_called_once_with(state='WY', county='Fremont')
    assert result['status'] == 'partial'
    assert result['classification']['dataset_year'] == 2024
    assert result['nearest_distance_summary']['hospital_count'] == 2
    assert result['hospitals'][0]['other_same_county_hospital_count'] == 1


def test_county_targets_keep_urban_out_of_county_neighbors(sources):
    result = service.analyze_area_access('WY', 'Fremont County', year=2023)
    assert result['coverage']['area_hospital_count'] == 2
    assert result['coverage']['unknown_classification_count'] == 0
    assert result['hospitals'][0]['distance_analysis']['candidate_count'] == 3
    assert sources[2].call_count == 2
    assert sources[3].call_count == 4
    sources[1].assert_not_called()
    assert result['status'] == 'complete'
    assert result['classification']['dataset_year'] == 2023


def test_all_hospitals_bypass_rural_classification(sources):
    result = service.analyze_area_access('WY', rural_only=False)
    assert result['coverage']['selected_hospital_count'] == 4
    assert len(result['counties']) == 2
    sources[2].assert_not_called()
    sources[1].assert_not_called()
    assert result['classification']['applied'] is False


def test_empty_county_is_not_no_healthcare(sources):
    result = service.analyze_area_access('WY', 'Unknown County')
    assert result['coverage']['area_hospital_count'] == 0
    assert result['hospitals'] == []
    assert result['nearest_distance_summary'] is None
    sources[1].assert_not_called()
    sources[3].assert_not_called()


def test_missing_classification_source_preserves_unknowns(sources):
    sources[1].side_effect = requests.RequestException('offline')
    result = service.analyze_area_access('WY')
    assert result['coverage']['unknown_classification_count'] == 4
    assert result['coverage']['excluded_urban_count'] == 0
    assert result['status'] == 'partial'
    sources[3].assert_not_called()


def test_county_failure_keeps_distance(sources):
    sources[4].side_effect = requests.RequestException('census offline')
    result = service.analyze_area_access('WY', 'Fremont')
    assert result['counties']['fremont']['demographics']['available'] is False
    assert result['counties']['fremont']['primary_care_hpsa']['available'] is True
    assert result['coverage']['distance_available_count'] == 2
    assert result['status'] == 'partial'


def test_geocoding_failure_only_attempted_once_per_state_hospital(sources):
    def geocode(item):
        if item['facility_id'] == '003':
            raise requests.RequestException('no coordinates')
        return {'latitude': 42, 'longitude': -108}
    sources[3].side_effect = geocode
    result = service.analyze_area_access('WY', 'Fremont')
    assert sources[3].call_count == 4
    for hospital in result['hospitals']:
        assert hospital['distance_analysis']['candidate_count'] == 2
        assert hospital['distance_analysis']['skipped_geocoding_count'] == 1


def test_target_coordinates_unavailable(sources):
    sources[3].return_value = None
    sources[3].side_effect = None
    result = service.analyze_area_access('WY', 'Fremont')
    assert result['coverage']['distance_available_count'] == 0
    assert result['nearest_distance_summary'] is None
    assert result['counties']['fremont']['demographics']['available'] is True


def test_invalid_filters_do_not_query(sources):
    for kwargs in ({'state': 'ZZ'}, {'state': 'WY', 'county': 'County'},
                   {'state': 'WY', 'year': True}, {'state': 'WY', 'rural_only': 'yes'}):
        with pytest.raises(ValueError):
            service.analyze_area_access(**kwargs)
    sources[0].assert_not_called()


def test_duplicate_state_records_and_other_state_not_counted(sources):
    sources[0].return_value = [row('001'), row('001'), row('002', state='WI')]
    result = service.analyze_area_access('WY')
    assert result['coverage']['state_hospital_count'] == 1
    assert result['nearest_distance_summary'] is None
    assert result['hospitals'][0]['distance_analysis']['candidate_count'] == 0


def test_area_result_clears_old_target_and_creates_card(sources):
    result = service.analyze_area_access('WY')
    assert extract_facility(result) == (None, True)
    assert extract_facility({'report_kind': 'area_healthcare_access', 'error': 'offline'}) == (None, True)
    assert evidence_summary(result)[0]['key'] == 'area_access'


def test_tool_registered_and_failure_not_empty_success(sources):
    from app.tools.agent_tools import analyze_area_healthcare_access, HOSPITAL_AGENT_TOOLS
    assert analyze_area_healthcare_access in HOSPITAL_AGENT_TOOLS
    sources[0].side_effect = requests.RequestException('directory offline')
    result = analyze_area_healthcare_access.invoke({'state': 'WY'})
    assert result['status'] == 'unavailable'
    assert 'coverage' not in result


def test_complete_area_card_uses_supported_status(sources):
    result = service.analyze_area_access('WY', 'Fremont')
    assert evidence_summary(result)[0]['status'] == 'available'



def test_zip_targets_keep_neighbors_outside_zip(sources):
    rows = [row('001'), row('002'), row('003', 'Natrona')]
    rows[0]['zip_code'] = '53948'
    rows[1]['zip_code'] = '53948-1234'
    rows[2]['zip_code'] = '53949'
    sources[0].return_value = rows
    result = service.analyze_area_access('WY', zip_code='53948', rural_only=False)
    assert result['area']['zip_code'] == '53948'
    assert result['coverage']['area_hospital_count'] == 2
    assert result['hospitals'][0]['distance_analysis']['candidate_count'] == 2
    assert sources[3].call_count == 3
    assert len(result['counties']) == 1


def test_zip_and_county_filters_intersect(sources):
    rows = [row('001'), row('002', 'Natrona')]
    for item in rows:
        item['zip_code'] = '53948'
    sources[0].return_value = rows
    result = service.analyze_area_access('WY', county='Fremont', zip_code='53948')
    assert result['coverage']['area_hospital_count'] == 1
    assert result['hospitals'][0]['facility_id'] == '001'
    assert result['hospitals'][0]['distance_analysis']['candidate_count'] == 1


def test_zip_can_represent_multiple_counties(sources):
    rows = [row('001'), row('002', 'Natrona')]
    for item in rows:
        item['zip_code'] = '53948'
    sources[0].return_value = rows
    result = service.analyze_area_access('WY', zip_code='53948', rural_only=False)
    assert len(result['counties']) == 2
    assert sources[4].call_count == 2
    assert sources[5].call_count == 2


def test_zip_preserves_leading_zero_and_exact_match(sources):
    rows = [row('001', state='MA'), row('002', state='MA'), row('003', state='MA')]
    rows[0]['zip_code'] = '01234'
    rows[1]['zip_code'] = '01234oops'
    rows[2]['zip_code'] = '12345'
    sources[0].return_value = rows
    result = service.analyze_area_access('MA', zip_code=' 01234 ', rural_only=False)
    assert result['area']['zip_code'] == '01234'
    assert result['coverage']['area_hospital_count'] == 1
    assert result['hospitals'][0]['zip_code'] == '01234'


def test_invalid_zip_fails_before_network(sources):
    for value in (12345, '', '1234', '123456', '12345-1234', 'abcde', '１２３４５'):
        with pytest.raises(ValueError):
            service.analyze_area_access('WY', zip_code=value)
    sources[0].assert_not_called()


def test_unmatched_zip_skips_classification_and_geocoding(sources):
    result = service.analyze_area_access('WY', zip_code='99999')
    assert result['coverage']['area_hospital_count'] == 0
    assert result['hospitals'] == []
    assert result['counties'] == {}
    sources[2].assert_not_called()
    sources[3].assert_not_called()


def test_zip_tool_forwards_filter(sources):
    from app.tools.agent_tools import analyze_area_healthcare_access
    with patch.object(service, 'analyze_area_access', return_value={'status': 'complete'}) as analyze:
        analyze_area_healthcare_access.invoke({'state': 'WI', 'zip_code': '53948', 'rural_only': False})
    analyze.assert_called_once_with('WI', None, False, None, zip_code='53948')
