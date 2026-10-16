"""Offline address-based access integration tests. No real facility address used."""
import unittest
from unittest.mock import patch, Mock
import requests
from app.services import facility_access_service as svc


class FacilityAccessTests(unittest.TestCase):
    def setUp(self):
        self.args = dict(facility_name='Test Health Center', address='1 Example St',
                         city='Test City', state='WI', zip_code='53900', address_verified=True)
        self.match = dict(coordinates={'x': -89, 'y': 44}, matchedAddress='1 EXAMPLE ST',
                          addressComponents={'state': 'WI'}, geographies={'Counties': [
                              {'NAME': 'Test County', 'STATE': '55', 'GEOID': '55001'}]})
        self.get = self.patch('requests.get')
        self.get.return_value = Mock()
        self.get.return_value.json.return_value = {'result': {'addressMatches': [self.match]}}
        self.demographics = self.patch('get_county_demographics', return_value={'total_population': 100, 'source': 'test'})
        self.hpsa = self.patch('get_county_primary_care_hpsa', return_value={'has_active_primary_care_hpsa': False})
        self.hospitals = self.patch('get_hospitals_by_state', return_value=[{'facility_id': '1'}, {'facility_id': '2'}, {'facility_id': '3'}])
        self.geocode = self.patch('geocode_hospital_record', side_effect=[
            dict(facility_id='1', latitude=45, longitude=-89),
            dict(facility_id='2', latitude=44.5, longitude=-89), None])

    def patch(self, name, **kwargs):
        p = patch('app.services.facility_access_service.' + name, **kwargs)
        self.addCleanup(p.stop)
        return p.start()

    def test_success_ranking_and_county(self):
        result = svc.analyze_facility_access(**self.args)
        self.assertTrue(result['location']['available'])
        self.demographics.assert_called_once_with(state_fips='55', county_name='Test County')
        self.assertEqual(result['target_facility']['address_verification'], 'user_confirmed')
        self.assertNotIn('facility_id', result['target_facility'])
        distance = result['distance_analysis']
        self.assertEqual([h['facility_id'] for h in distance['nearest_hospitals']], ['2', '1'])
        self.assertEqual((distance['candidate_count'], distance['skipped_geocoding_count']), (2, 1))

    def test_validation_before_network(self):
        for changes in ({'address_verified': False}, {'address': ''}, {'state': 'ZZ'}, {'zip_code': 'bad'}):
            with self.subTest(changes=changes):
                self.assertIn('error', svc.analyze_facility_access(**(self.args | changes)))
        self.get.assert_not_called()

    def test_no_or_ambiguous_match(self):
        for matches in ([], [self.match, self.match]):
            self.get.return_value.json.return_value = {'result': {'addressMatches': matches}}
            result = svc.analyze_facility_access(**self.args)
            self.assertFalse(result['location']['available'])
        self.hospitals.assert_not_called()

    def test_geocoder_failure(self):
        self.get.side_effect = requests.Timeout('timeout')
        self.assertFalse(svc.analyze_facility_access(**self.args)['location']['available'])

    def test_independent_failures_preserve_other_evidence(self):
        self.demographics.side_effect = ValueError('No Census key')
        self.hpsa.side_effect = requests.Timeout('timeout')
        result = svc.analyze_facility_access(**self.args)
        self.assertTrue(result['distance_analysis']['available'])
        self.assertFalse(result['county_demographics']['available'])
        self.assertFalse(result['primary_care_hpsa']['available'])

    def test_missing_county_keeps_distance(self):
        self.match['geographies'] = {}
        result = svc.analyze_facility_access(**self.args)
        self.assertFalse(result['county_demographics']['available'])
        self.assertTrue(result['distance_analysis']['available'])

    def test_wrong_state_stops_analysis(self):
        self.match['geographies']['Counties'][0]['STATE'] = '54'
        self.assertFalse(svc.analyze_facility_access(**self.args)['location']['available'])
        self.hospitals.assert_not_called()

    def test_distance_failure_preserves_county(self):
        self.hospitals.side_effect = requests.Timeout('timeout')
        result = svc.analyze_facility_access(**self.args)
        self.assertFalse(result['distance_analysis']['available'])
        self.assertTrue(result['county_demographics']['available'])

    def test_empty_candidates(self):
        self.hospitals.return_value = []
        distance = svc.analyze_facility_access(**self.args)['distance_analysis']
        self.assertTrue(distance['available'])
        self.assertEqual(distance['nearest_hospitals'], [])


if __name__ == '__main__':
    unittest.main()
