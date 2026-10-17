"""Offline checks for compact resolution, source failures and target switching."""
import unittest
from unittest.mock import patch
from requests import RequestException
from app.models.hospital import Hospital
from app.services import facility_resolution_service as service
from app.services.chat_context import extract_facility


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        self.hospital = Hospital(facility_id='520109', facility_name='Mile Bluff',
            citytown='Mauston', state='WI', zip_code='53948',
            countyparish='Juneau', hospital_type='Acute Care')
        self.local = patch.object(service, 'search_tribal_facilities', return_value={'count': 0})
        self.cms = patch.object(service, 'search_hospitals_by_name', return_value=[self.hospital])
        self.local.start()
        self.search = self.cms.start()
        self.addCleanup(self.local.stop)
        self.addCleanup(self.cms.stop)

    def test_resolved_and_filters(self):
        result = service.resolve_facility_identity('Mile Bluff', 'WI', 'Juneau')
        self.search.assert_called_once_with('Mile Bluff', 'WI', 'Juneau')
        self.assertEqual(result['resolution_status'], 'resolved_hospital')
        self.assertNotIn('historical_matches', result)
        self.assertEqual(extract_facility(result)[0]['facility_id'], '520109')

    def test_ambiguity_and_bounded_payload(self):
        self.search.return_value = [self.hospital] * 5
        result = service.resolve_facility_identity('Mile')
        self.assertEqual(result['candidate_count'], 5)
        self.assertEqual(len(result['candidates']), 3)
        self.assertEqual(extract_facility(result), (None, True))

    def test_historical_not_financial_identity(self):
        self.search.return_value = []
        with patch.object(service, 'search_tribal_facilities', return_value={
            'count': 1, 'source_created_date': '2020-01-26', 'facilities': [{
                'facility_name': 'Clinic', 'facility_type': 'FQHC', 'city': 'Town',
                'state': 'WI', 'listed_ccns': ['521812'], 'citation_url': 'https://www.cms.gov/test#page=2'}]}):
            result = service.resolve_facility_identity('Clinic', 'WI', 'Juneau')
        self.assertFalse(result['can_analyze_hospital_financials'])
        self.assertNotIn('listed_ccns', result['historical_matches'][0])
        self.assertEqual(extract_facility(result), (None, True))

    def test_cms_failure_not_absence(self):
        self.search.side_effect = RequestException('offline')
        self.assertEqual(service.resolve_facility_identity('Clinic')['resolution_status'], 'unavailable')

    def test_local_failure_does_not_block_cms(self):
        with patch.object(service, 'search_tribal_facilities', side_effect=OSError()):
            self.assertEqual(service.resolve_facility_identity('Mile')['resolution_status'], 'resolved_hospital')

    def test_direct_ccn_and_invalid_modes(self):
        with patch.object(service, 'get_hospital_by_id', return_value=self.hospital) as lookup:
            result = service.resolve_facility_identity(facility_id='520109')
        lookup.assert_called_once_with('520109')
        self.assertTrue(result['can_analyze_hospital_financials'])
        self.assertIn('error', service.resolve_facility_identity())
        self.assertIn('error', service.resolve_facility_identity('Mile', facility_id='520109'))

    def test_registry_consolidated(self):
        from app.tools.agent_tools import HOSPITAL_AGENT_TOOLS
        names = []
        for tool in HOSPITAL_AGENT_TOOLS:
            names.append(tool.name)
        self.assertIn('resolve_facility', names)
        self.assertNotIn('search_hospital', names)
        self.assertNotIn('get_hospital_by_ccn', names)


if __name__ == '__main__':
    unittest.main()
