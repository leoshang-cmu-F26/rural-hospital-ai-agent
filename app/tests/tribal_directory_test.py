from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import hashlib
import json
import sqlite3
import unittest

from app.services import tribal_directory_service as directory
from app.services.chat_context import extract_facility
from app.services.evidence_summary import evidence_summary
from app.services.agent_progress import ToolProgressHandler


class TribalDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'data' / 'directory.db'
        patcher = patch.object(directory, 'TRIBAL_DIRECTORY_DB_PATH', self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_wisconsin_records_have_type_date_and_pages(self):
        result = directory.search_tribal_facilities(state='Wisconsin')
        self.assertEqual(result['count'], 2)
        self.assertTrue(result['historical_snapshot'])
        self.assertEqual(result['source_created_date'], '2020-01-26')
        first = result['facilities'][0]
        self.assertEqual(first['facility_name'], 'MENOMINEE TRIBAL CLINIC')
        self.assertEqual(first['facility_type'], 'FQHC')
        self.assertEqual(first['listed_ccns'], ['521812'])
        self.assertEqual(first['source_page'], 2)
        self.assertFalse(first['listed_as_hospital'])
        self.assertFalse(first['current_status_verified'])
        self.assertNotIn('facility_id', first)

    def test_filters_do_not_silently_relax(self):
        self.assertEqual(directory.search_tribal_facilities(name='Menominee', state='MN')['count'], 0)
        self.assertEqual(directory.search_tribal_facilities(name='Menominee', state='WI', city='Keshena')['count'], 1)
        self.assertEqual(directory.search_tribal_facilities(state='WI', facility_type='Hospital')['count'], 0)

    def test_multi_ccn_and_leading_zeros_survive(self):
        result = directory.search_tribal_facilities(name='United Indian Health Services', state='CA')
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['facilities'][0]['listed_ccns'], ['051165', '051163', '051164', '051167', '051166'])
        self.assertEqual(result['facilities'][0]['city'], 'Multiple Locations')

    def test_index_is_persistent_and_not_duplicated(self):
        first = directory.search_tribal_facilities(state='WI')
        second = directory.search_tribal_facilities(state='WI')
        self.assertEqual(first, second)
        self.assertTrue(self.db.exists())
        with closing(sqlite3.connect(self.db)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM tribal_facilities').fetchone()[0], 163)

    def test_counts_and_pdf_fingerprint(self):
        data = json.loads(directory.TRIBAL_DIRECTORY_SEED_PATH.read_text(encoding='utf-8'))
        pdf = directory.TRIBAL_DIRECTORY_SEED_PATH.with_suffix('.pdf')
        self.assertEqual(hashlib.sha256(pdf.read_bytes()).hexdigest(), data['source_sha256'])
        self.assertEqual(data['record_count'], 163)
        self.assertEqual(data['ccn_count'], 171)
        self.assertEqual(data['record_counts_by_type']['Hospital'], 42)
        self.assertEqual(data['record_counts_by_type']['FQHC'], 100)

    def test_limit_and_missing_match(self):
        result = directory.search_tribal_facilities(facility_type='FQHC', limit=5)
        self.assertEqual((result['count'], result['returned_count'], result['truncated']), (100, 5, True))
        empty = directory.search_tribal_facilities(name='Ho-Chunk', state='WI')
        self.assertEqual(empty['count'], 0)
        self.assertIn('does not establish', ' '.join(empty['limitations']))

    def test_validation_and_no_unfiltered_dump(self):
        for args in ({}, {'state': 'ZZ'}, {'name': ' '}, {'state': 'WI', 'limit': 100}):
            self.assertIn('error', directory.search_tribal_facilities(**args))
        self.assertFalse(self.db.exists())

    def test_historical_lookup_clears_current_hospital_context(self):
        result = directory.search_tribal_facilities(state='WI')
        self.assertEqual(extract_facility(result), (None, True))
        events = []
        ToolProgressHandler(events.append).on_tool_end(result)
        context = next(event for event in events if event['type'] == 'context')
        self.assertIsNone(context['current_facility'])

    def test_ui_source_card_is_explicitly_historical(self):
        rows = evidence_summary(directory.search_tribal_facilities(state='WI'))
        self.assertEqual(rows[0]['period'], '2020-01-26')
        self.assertEqual(rows[0]['status'], 'partial')
        self.assertIn('unverified', rows[0]['details'])

    def test_tool_registration_and_missing_snapshot_is_not_zero(self):
        from app.tools.agent_tools import search_tribal_facility_directory, HOSPITAL_AGENT_TOOLS
        self.assertIn('search_tribal_facility_directory', [tool.name for tool in HOSPITAL_AGENT_TOOLS])
        with patch.object(directory, 'TRIBAL_DIRECTORY_SEED_PATH', Path(self.temp.name) / 'missing.json'):
            result = search_tribal_facility_directory.invoke({'state': 'WI'})
        self.assertIn('error', result)
        self.assertNotIn('count', result)


if __name__ == '__main__':
    unittest.main()
