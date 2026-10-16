import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from app.services.chat_stream import stream_agent_events
from app.services.agent_progress import report_progress


class ChatStreamTests(unittest.TestCase):
    def test_real_callbacks_progress_and_result(self):
        def runner(message, callbacks):
            callbacks[0].on_tool_start({'name': 'search_hospital'}, 'private input')
            report_progress('Querying county evidence…')
            callbacks[0].on_tool_end('private result')
            return 'Answer for ' + message
        events = [json.loads(line) for line in stream_agent_events('test', runner)]
        self.assertEqual(events[-1], {'type': 'result', 'response': 'Answer for test'})
        self.assertTrue(any(e.get('message') == 'Searching CMS hospital records…' for e in events))
        self.assertTrue(any(e.get('message') == 'Querying county evidence…' for e in events))
        self.assertNotIn('private', json.dumps(events))

    def test_error_finishes_without_leaking_details(self):
        def runner(message, callbacks):
            raise RuntimeError('private diagnostic')
        with self.assertLogs('app.services.chat_stream', level='ERROR'):
            events = [json.loads(line) for line in stream_agent_events('test', runner)]
        self.assertEqual(events[-1]['type'], 'error')
        self.assertNotIn('private diagnostic', json.dumps(events))

    def test_parallel_requests_keep_progress_separate(self):
        def runner(message, callbacks):
            report_progress(message)
            return message
        def collect(message):
            return [json.loads(line) for line in stream_agent_events(message, runner)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(collect, ['request-one', 'request-two']))
        self.assertNotIn('request-two', json.dumps(first))
        self.assertNotIn('request-one', json.dumps(second))


if __name__ == '__main__':
    unittest.main()
