"""Offline regression coverage for filtered search and composite investigation."""
import unittest
from unittest.mock import patch, Mock
import requests
from app.services import cms_service as cms
from app.services.investigation_service import build_hospital_investigation
from app.services.evidence_summary import evidence_summary
from app.services.chat_context import extract_facility


def hospital(ccn='520109', name='MILE BLUFF MEDICAL CENTER', state='WI', county='JUNEAU'):
    return dict(facility_id=ccn, facility_name=name, citytown='MAUSTON',
                state=state, countyparish=county, zip_code='53948',
                hospital_type='Acute Care Hospitals')


class SearchTests(unittest.TestCase):
    def setUp(self):
        cms.STATE_HOSPITAL_CACHE.clear()
        self.addCleanup(cms.STATE_HOSPITAL_CACHE.clear)

    def test_name_state_county_normalization(self):
        with patch.object(cms, 'get_hospitals_by_state', return_value=[hospital(),
                hospital('000001', state='MN'), hospital('000002', county='SAUK')]) as lookup:
            result = cms.search_hospitals_by_name('Mile-Bluff Medical Center', 'Wisconsin', ' Juneau County ')
        lookup.assert_called_once_with('WI')
        self.assertEqual([h.facility_id for h in result], ['520109'])

    def test_county_filter_without_state(self):
        with patch.object(cms, '_query_hospital_rows', return_value=[hospital(), hospital('000002', county='SAUK')]):
            self.assertEqual(len(cms.search_hospitals_by_name('Mile Bluff', county='Juneau')), 1)

    def test_does_not_drop_location_or_guess_alias(self):
        with patch.object(cms, 'get_hospitals_by_state', return_value=[hospital()]):
            self.assertEqual(cms.search_hospitals_by_name('Mile Bluff', 'WI', 'Sauk'), [])
            self.assertEqual(cms.search_hospitals_by_name('Old Unknown Name', 'WI'), [])

    def test_ambiguous_results_remain_ambiguous(self):
        with patch.object(cms, 'get_hospitals_by_state', return_value=[hospital(), hospital('520110')]):
            self.assertEqual(len(cms.search_hospitals_by_name('Mile Bluff', 'WI')), 2)

    def test_pagination_and_duplicate_records(self):
        page = [hospital(str(i)) for i in range(500)]
        with patch.object(cms.requests, 'get') as get:
            get.side_effect = [Mock(json=lambda: {'results': page}),
                               Mock(json=lambda: {'results': [page[0], hospital('last')]})]
            result = cms.get_hospitals_by_state('WI')
        self.assertEqual(len(result), 501)
        self.assertEqual(get.call_args.kwargs['params']['offset'], 500)

    def test_repeating_page_does_not_return_false_complete_list(self):
        with patch.object(cms.requests, 'get') as get:
            get.return_value.json.return_value = {'results': [hospital(str(i)) for i in range(500)]}
            with self.assertRaises(requests.RequestException):
                cms.get_hospitals_by_state('WI')
        self.assertNotIn('WI', cms.STATE_HOSPITAL_CACHE)

    def test_invalid_filters_fail_before_network(self):
        with patch.object(cms.requests, 'get') as get:
            for args in (('', None, None), ('Mile', 'ZZ', None), ('Mile', 'WI', 'County')):
                with self.assertRaises(ValueError):
                    cms.search_hospitals_by_name(*args)
            get.assert_not_called()


class InvestigationTests(unittest.TestCase):
    def setUp(self):
        p = patch('app.services.investigation_service.get_hospital_by_id',
                  return_value=cms.Hospital(**hospital()))
        p.start(); self.addCleanup(p.stop)
        self.financial = Mock(return_value={'report_year': 2024, 'source': 'CMS',
                                            'indicators': {'operating_margin': -.2, 'missing_fields': []}})
        self.trend = Mock(return_value={'years_with_data': [2023, 2024],
                                       'years_without_report': [], 'years_unavailable': {}})
        self.access = Mock(return_value={key: {'available': True} for key in (
            'county_demographics', 'primary_care_hpsa', 'distance_analysis')})

    def run_report(self, **kwargs):
        return build_hospital_investigation('520109', self.financial, self.trend, self.access, **kwargs)

    def test_all_sections_and_periods_preserved(self):
        result = self.run_report(start_year=2020, end_year=2024)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['financials']['report_year'], 2024)
        self.assertEqual(result['financials']['indicators']['operating_margin'], -.2)
        self.trend.assert_called_once_with(facility_id='520109', start_year=2020, end_year=2024)
        self.financial.assert_called_once_with(facility_id='520109')
        facility, _ = extract_facility(result)
        self.assertEqual(facility['facility_id'], '520109')

    def test_failure_in_one_section_preserves_others(self):
        self.financial.side_effect = requests.Timeout('test')
        result = self.run_report()
        self.assertFalse(result['financials']['available'])
        self.assertTrue(result['financial_trend']['available'])
        self.assertTrue(result['healthcare_access']['available'])
        self.assertEqual(result['status'], 'partial')

    def test_nested_missing_data_is_partial(self):
        self.access.return_value['county_demographics'] = {'available': False, 'error': 'No key'}
        self.access.return_value['distance_analysis']['skipped_geocoding_count'] = 18
        result = self.run_report()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(result['data_gaps']), 2)

    def test_no_hospital_does_not_analyze_other_data(self):
        with patch('app.services.investigation_service.get_hospital_by_id', return_value=None):
            self.assertIn('error', self.run_report())
        self.financial.assert_not_called()

    def test_invalid_year_order(self):
        self.assertIn('error', self.run_report(start_year=2024, end_year=2020))
        self.financial.assert_not_called()

    def test_tool_error_dict_preserves_details(self):
        self.trend.return_value = {'error': 'No reports', 'years_without_report': [2022]}
        result = self.run_report()
        self.assertFalse(result['financial_trend']['available'])
        self.assertEqual(result['financial_trend']['years_without_report'], [2022])

    def test_unavailable_county_is_not_a_zero_count_finding(self):
        from app.services import access_service
        target = cms.Hospital(**hospital())
        target.countyparish = None
        with patch.object(access_service, 'compare_hospitals_in_area', return_value={'error': 'County unavailable'}), \
             patch.object(access_service, 'get_hospital_by_id', return_value=target), \
             patch.object(access_service, 'get_hospital_demographics', return_value={'error': 'County unavailable'}), \
             patch.object(access_service, 'get_nearest_hospitals', return_value={'nearest_hospitals': []}):
            result = access_service.get_healthcare_access_analysis('520109')
        self.assertFalse(result['county_comparison_available'])
        self.assertIsNone(result['alternative_hospital_count'])
        self.assertTrue(result['distance_analysis']['available'])
        self.assertFalse(result['primary_care_hpsa']['available'])

    def test_county_comparison_gap_is_retained_in_full_report(self):
        self.access.return_value.update(county_comparison_available=False,
                                         county_comparison_error='County unavailable')
        result = self.run_report()
        self.assertEqual(result['status'], 'partial')
        self.assertTrue(any(gap['section'] == 'county_comparison' for gap in result['data_gaps']))


class EvidenceTests(unittest.TestCase):
    def test_sources_years_and_gaps_are_structured(self):
        rows = evidence_summary({'financials': {'available': True, 'report_year': 2024,
            'fiscal_year_begin': '2023-10-01', 'fiscal_year_end': '2024-09-30',
            'indicators': {'missing_fields': ['total_assets']}},
            'financial_trend': {'available': False, 'error': 'Unavailable'},
            'healthcare_access': {'available': True, 'distance_analysis': {
                'available': True, 'skipped_geocoding_count': 18, 'nearest_hospitals': [{}]}}})
        self.assertEqual(rows[0]['period'], '2024')
        self.assertEqual(rows[0]['status'], 'partial')
        self.assertEqual(rows[1]['status'], 'unavailable')
        self.assertIn('18 hospitals', rows[2]['details'])

    def test_ignores_unknown_and_private_payloads(self):
        self.assertEqual(evidence_summary('private reasoning'), [])
        self.assertEqual(evidence_summary({'large_private_data': 'secret'}), [])

    def test_real_tools_registered_and_search_metadata(self):
        from app.tools.agent_tools import search_hospital, HOSPITAL_AGENT_TOOLS
        with patch('app.tools.agent_tools.search_hospitals_by_name',
                   return_value=[cms.Hospital(**hospital(str(i))) for i in range(7)]):
            result = search_hospital.invoke({'name':'Mile', 'state':'WI', 'county':'Juneau'})
        self.assertEqual((result['count'], result['returned_count'], result['truncated']), (7, 5, True))
        self.assertIn('investigate_hospital', [tool.name for tool in HOSPITAL_AGENT_TOOLS])


if __name__ == '__main__':
    unittest.main()
