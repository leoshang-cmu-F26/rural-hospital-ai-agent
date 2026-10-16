import json
import unittest
from unittest.mock import Mock, patch
import requests
from pydantic import ValidationError
from app.agents.agent import AgentRequest
from app.models.hospital import Hospital
from app.services.comparison_service import compare_hospitals
from app.services.chat_context import build_messages, extract_comparison
from app.services.chat_stream import stream_agent_events
from app.services.evidence_summary import evidence_summary


def identity(ccn):
    return Hospital(facility_id=ccn, facility_name='Hospital '+ccn,
                    citytown='Test', state='WI', zip_code='53948',
                    countyparish='TEST', hospital_type='Acute Care Hospitals')


def financial(ccn, year, begin=None, end=None):
    return {'report_year': year, 'fiscal_year_begin': begin or f'{year}-01-01',
            'fiscal_year_end': end or f'{year}-12-31', 'source': 'CMS',
            'indicators': {'facility_id': ccn, 'hospital_name': 'Hospital '+ccn,
                           'operating_margin': -20 if ccn == '010001' else -10,
                           'occupancy_rate': 20, 'liability_to_asset_ratio': 50,
                           'cost_to_charge_ratio': .4, 'missing_fields': []}}


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        p = patch('app.services.comparison_service.get_hospital_by_id', side_effect=identity)
        p.start(); self.addCleanup(p.stop)
        p = patch('app.services.comparison_service.get_available_report_years', return_value=[2022, 2023, 2024])
        p.start(); self.addCleanup(p.stop)
        self.financial = Mock(side_effect=lambda facility_id, year: financial(facility_id, year))
        self.trend = Mock(return_value={'years_with_data': [2023, 2024]})
        self.access = Mock(return_value={key: {'available': True} for key in (
            'county_demographics', 'primary_care_hpsa', 'distance_analysis')})

    def compare(self, **kwargs):
        return compare_hospitals('010001', '010002', self.financial,
                                 self.trend, self.access, **kwargs)

    def test_latest_common_and_difference_direction(self):
        result = self.compare()
        self.assertEqual(result['financial_alignment']['common_report_year'], 2024)
        self.assertEqual(result['financial_differences'][0]['second_minus_first'], 10)
        self.assertEqual(result['financial_differences'][0]['unit'], 'percentage_points')
        self.assertEqual(len(result['hospital_reports']), 2)
        self.assertEqual(self.financial.call_count, 2)

    def test_walk_back_when_one_report_missing(self):
        self.financial.side_effect = lambda facility_id, year: (
            {'error': 'Financial data not found'} if facility_id == '010002' and year == 2024
            else financial(facility_id, year))
        result = self.compare()
        self.assertEqual(result['financial_alignment']['common_report_year'], 2023)
        self.assertEqual([r['financials']['report_year'] for r in result['hospital_reports']], [2023, 2023])
        self.assertEqual(result['financial_alignment']['newer_years_with_unresolved_data'], [])

    def test_newer_failed_lookup_is_not_a_definitive_latest_claim(self):
        def lookup(facility_id, year):
            if facility_id == '010001' and year == 2024:
                raise requests.Timeout('timeout')
            return financial(facility_id, year)
        self.financial.side_effect = lookup
        result = self.compare()
        self.assertEqual(result['financial_alignment']['common_report_year'], 2023)
        self.assertEqual(result['financial_alignment']['newer_years_with_unresolved_data'], [2024])
        self.assertEqual(result['status'], 'partial')

    def test_no_common_year_keeps_separate_periods_without_deltas(self):
        self.financial.side_effect = lambda facility_id, year: (
            financial(facility_id, year) if (facility_id, year) in [('010001', 2024), ('010002', 2023)]
            else {'error': 'Financial data not found'})
        result = self.compare()
        self.assertIsNone(result['financial_alignment']['common_report_year'])
        self.assertEqual(result['financial_differences'], [])
        self.assertEqual([r['financials']['report_year'] for r in result['hospital_reports']], [2024, 2023])

    def test_fiscal_mismatch_prevents_deltas(self):
        self.financial.side_effect = lambda facility_id, year: financial(
            facility_id, year, begin='2023-10-01' if facility_id=='010002' else None)
        result = self.compare()
        self.assertFalse(result['financial_alignment']['fiscal_periods_match'])
        self.assertEqual(result['financial_differences'], [])

    def test_unknown_fiscal_period_prevents_deltas(self):
        def lookup(facility_id, year):
            data = financial(facility_id, year)
            data['fiscal_year_begin'] = None
            return data
        self.financial.side_effect = lookup
        self.assertEqual(self.compare()['financial_differences'], [])

    def test_requested_year_and_trend_bounds_stay_separate(self):
        result = self.compare(year=2022, start_year=2020, end_year=2024)
        self.assertEqual(result['financial_alignment']['common_report_year'], 2022)
        self.trend.assert_any_call(facility_id='010001', start_year=2020, end_year=2024)
        self.assertEqual(self.financial.call_count, 2)

    def test_one_hospital_access_failure_preserves_other_sections(self):
        self.access.side_effect = [requests.Timeout('timeout'), {'county_demographics': {'available': True}}]
        result = self.compare()
        self.assertFalse(result['hospital_reports'][0]['healthcare_access']['available'])
        self.assertTrue(result['hospital_reports'][1]['healthcare_access']['available'])
        self.assertTrue(result['hospital_reports'][0]['financials']['available'])

    def test_missing_indicator_not_substituted_with_zero(self):
        def lookup(facility_id, year):
            data=financial(facility_id, year)
            data['indicators']['operating_margin']=None
            data['indicators']['missing_fields']=['operating_margin']
            return data
        self.financial.side_effect=lookup
        self.assertNotIn('operating_margin', [d['metric'] for d in self.compare()['financial_differences']])

    def test_same_ccn_and_unknown_hospital_rejected(self):
        self.assertIn('error', compare_hospitals('010001', '010001', self.financial, self.trend, self.access))
        with patch('app.services.comparison_service.get_hospital_by_id', return_value=None):
            self.assertIn('error', self.compare())
        self.financial.assert_not_called()

    def test_tool_and_two_identity_context(self):
        from app.tools.agent_tools import HOSPITAL_AGENT_TOOLS
        self.assertIn('compare_hospital_investigations', [t.name for t in HOSPITAL_AGENT_TOOLS])
        result = self.compare()
        pair = extract_comparison(result)
        self.assertEqual([f['facility_id'] for f in pair], ['010001', '010002'])
        self.assertNotIn('financials', json.dumps(pair))
        request = AgentRequest(message='Compare their trends', comparison_facilities=pair)
        messages = build_messages(request.message, comparison_facilities=request.comparison_facilities)
        self.assertIn('010001', messages[0]['content'])
        self.assertIn('010002', messages[0]['content'])
        with self.assertRaises(ValidationError):
            AgentRequest(message='test', comparison_facilities=pair + [pair[0]])

    def test_evidence_cards_keep_both_hospital_labels(self):
        rows = evidence_summary(self.compare())
        self.assertEqual(rows[0]['key'], 'comparison_alignment')
        self.assertTrue(any(r['key'].startswith('010001:') for r in rows))
        self.assertTrue(any(r['key'].startswith('010002:') for r in rows))
        self.assertTrue(any('Common-year financial report' in r['label'] for r in rows))

    def test_pair_not_extracted_from_neighbor_lists(self):
        self.assertEqual(extract_comparison({'comparison_hospitals': [identity('010001').model_dump(), identity('010002').model_dump()]}), [])

    def test_stream_forwards_pair_and_reports_new_pair(self):
        result = self.compare()
        pair = extract_comparison(result)
        def runner(message, callbacks, comparison_facilities):
            self.assertEqual(comparison_facilities, pair)
            callbacks[0].on_tool_end(result)
            return 'Comparison complete'
        events = [json.loads(line) for line in stream_agent_events('compare them', runner, comparison_facilities=pair)]
        event = next(e for e in events if e['type']=='comparison_context')
        self.assertEqual(event['comparison_facilities'], pair)
        self.assertEqual(events[-1]['type'], 'result')

    def test_http_routes_forward_validated_comparison_pair(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api import routes
        pair = extract_comparison(self.compare())
        app = FastAPI()
        app.include_router(routes.router)
        client = TestClient(app)
        with patch.object(routes, 'ask_hospital_agent', return_value='Comparison answer') as runner:
            body = {'message': 'Compare their finances', 'comparison_facilities': pair}
            self.assertEqual(client.post('/agent/chat', json=body).status_code, 200)
            self.assertEqual(runner.call_args.kwargs['comparison_facilities'][1].facility_id, '010002')
            result = client.post('/agent/chat/stream', json=body)
            self.assertIn('Comparison answer', result.text)
            self.assertEqual(runner.call_args.kwargs['comparison_facilities'][0].facility_id, '010001')


if __name__ == '__main__':
    unittest.main()
