"""Offline regression tests for both hospital coordinate cache layers."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import requests
from app.services import coordinate_cache as disk
from app.services import geocoding_service as service


class CoordinateCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'data' / 'coordinates.db'
        patcher = patch.object(disk, 'COORDINATE_DB_PATH', self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        service.HOSPITAL_COORDINATE_CACHE.clear()
        self.addCleanup(service.HOSPITAL_COORDINATE_CACHE.clear)
        self.record = dict(facility_id='010001', facility_name='Test Hospital',
                           address='1 Main St', citytown='Test City',
                           state='AL', zip_code='35000')
        self.coordinates = dict(latitude=32.0, longitude=-86.0,
                                matched_address=None,
                                source='U.S. Census Bureau Geocoder')

    def test_persistence_for_both_entry_points(self):
        for entry in ('id', 'record'):
            with self.subTest(entry=entry):
                service.HOSPITAL_COORDINATE_CACHE.clear()
                self.record['facility_id'] = '010001' if entry == 'id' else '010002'
                facility_id = self.record['facility_id']
                with patch.object(service, 'get_hospital_by_id', return_value=SimpleNamespace(**self.record)), patch.object(service, 'geocode_address', return_value=self.coordinates) as geocode:
                    first = (service.geocode_hospital(facility_id) if entry == 'id'
                             else service.geocode_hospital_record(self.record))
                    geocode.assert_called_once()
                self.assertTrue(self.path.exists())
                service.HOSPITAL_COORDINATE_CACHE.clear()
                with patch.object(service, 'get_hospital_by_id', side_effect=AssertionError('CMS called')), patch.object(service, 'geocode_address', side_effect=AssertionError('Census called')):
                    self.assertEqual(first, service.geocode_hospital(facility_id))
                    service.HOSPITAL_COORDINATE_CACHE.clear()
                    self.assertEqual(first, service.geocode_hospital_record(self.record))
                self.assertEqual(first, service.HOSPITAL_COORDINATE_CACHE[facility_id])
                with patch.object(service, 'read_coordinate_cache', side_effect=AssertionError('SQLite called')):
                    self.assertEqual(first, service.geocode_hospital(facility_id))
                    self.assertEqual(first, service.geocode_hospital_record(self.record))

    def test_initialize_miss_and_upsert(self):
        self.assertIsNone(disk.read_coordinate_cache('missing'))
        result = dict(self.record, **self.coordinates)
        result['city'] = result.pop('citytown')
        disk.write_coordinate_cache(result)
        result['latitude'] = 33.0
        disk.write_coordinate_cache(result)
        self.assertEqual(result, disk.read_coordinate_cache('010001'))

    def test_nearest_hospitals_reuses_persistent_coordinates(self):
        from app.services import distance_service as distance
        target = SimpleNamespace(**self.record)
        candidates = [dict(self.record, facility_id='010002'),
                      dict(self.record, facility_id='010003')]
        with patch.object(distance, 'get_hospital_by_id', return_value=target), patch.object(distance, 'get_hospitals_by_state', return_value=[self.record] + candidates), patch.object(service, 'get_hospital_by_id', return_value=target), patch.object(service, 'geocode_address', side_effect=[self.coordinates, dict(self.coordinates, latitude=34.0), dict(self.coordinates, latitude=33.0)]) as geocode:
            first = distance.get_nearest_hospitals('010001')
            self.assertEqual(geocode.call_count, 3)
            self.assertEqual([h['facility_id'] for h in first['nearest_hospitals']],
                             ['010003', '010002'])
            service.HOSPITAL_COORDINATE_CACHE.clear()
            geocode.side_effect = AssertionError('Census called after restart')
            self.assertEqual(first, distance.get_nearest_hospitals('010001'))

    def test_invalid_and_unmatched_records_are_not_cached(self):
        with patch.object(service, 'geocode_address', return_value=None) as geocode:
            self.assertIsNone(service.geocode_hospital_record({}))
            self.assertIsNone(service.geocode_hospital_record({'facility_id': 'empty'}))
            geocode.assert_not_called()
            self.assertIsNone(service.geocode_hospital_record(self.record))
        self.assertIsNone(disk.read_coordinate_cache('010001'))
        with patch.object(service, 'get_hospital_by_id', return_value=None):
            self.assertIsNone(service.geocode_hospital('missing'))

    def test_census_response_and_errors_unchanged(self):
        with patch.object(service.requests, 'get') as get:
            get.return_value.json.return_value = {'result': {'addressMatches': [
                {'coordinates': {'x': -86, 'y': 32}, 'matchedAddress': '1 MAIN ST'}]}}
            result = service.geocode_address('1 Main St', 'Test City', 'AL', '35000')
            self.assertEqual((result['latitude'], result['longitude']), (32.0, -86.0))
            self.assertEqual(get.call_args.kwargs['timeout'], 30)
            self.assertEqual(get.call_args.kwargs['params']['benchmark'], 'Public_AR_Current')
            get.return_value.json.return_value = {'result': {'addressMatches': []}}
            self.assertIsNone(service.geocode_address('a', 'b', 'c', 'd'))
            get.return_value.raise_for_status.side_effect = requests.HTTPError('failure')
            with self.assertRaises(requests.HTTPError):
                service.geocode_address('a', 'b', 'c', 'd')


if __name__ == '__main__':
    unittest.main()
