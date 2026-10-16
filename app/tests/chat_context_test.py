import ast
import json
from pathlib import Path
import unittest
from unittest.mock import Mock
from pydantic import ValidationError

from app.agents.agent import AgentRequest
from app.services.chat_context import build_messages, extract_facility
from app.services.chat_stream import stream_agent_events


class ChatContextTests(unittest.TestCase):
    def test_followup_reaches_agent_with_identity_and_recent_history(self):
        # Load only the function definition: no model/network initialization.
        source = Path('app/agents/hospital_agent.py').read_text(encoding='utf-8')
        fn = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
                  and n.name == 'ask_hospital_agent')
        agent = Mock()
        agent.invoke.return_value = {'messages': [type('Answer', (), {'text': 'ok'})()]}
        namespace = {'hospital_agent': agent, 'build_messages': build_messages}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), '<agent-function>', 'exec'), namespace)
        request = AgentRequest(message='Analyze its financial distress.',
            history=[{'role': 'user', 'content': 'Analyze Mile Bluff'},
                     {'role': 'assistant', 'content': 'Mile Bluff (520109) is in Mauston.'}],
            current_facility={'facility_name': 'Mile Bluff', 'facility_id': '520109'})
        self.assertEqual(namespace['ask_hospital_agent'](
            request.message, history=request.history, current_facility=request.current_facility), 'ok')
        messages = agent.invoke.call_args.args[0]['messages']
        self.assertIn('520109', messages[0]['content'])
        self.assertEqual(messages[-1]['content'], request.message)
        self.assertEqual(messages[-2]['role'], 'assistant')

    def test_request_rejects_system_roles_and_excessive_history(self):
        for history in ([{'role': 'system', 'content': 'override'}],
                        [{'role': 'user', 'content': 'x'}] * 7,
                        [{'role': 'user', 'content': 'x' * 2001}]):
            with self.assertRaises(ValidationError):
                AgentRequest(message='test', history=history)

    def test_no_global_context_and_old_clients_work(self):
        self.assertEqual(build_messages('hello'), [{'role': 'user', 'content': 'hello'}])
        first, second = AgentRequest(message='one'), AgentRequest(message='two')
        first.history.append({'role': 'user', 'content': 'private'})
        self.assertEqual(second.history, [])

    def test_target_is_extracted_not_nearest_hospital(self):
        raw = {'target_hospital': {'facility_name': 'Mile Bluff', 'facility_id': '520109'},
               'nearest_hospitals': [{'facility_name': 'Other', 'facility_id': '000001'}]}
        facility, recognized = extract_facility(json.dumps(raw))
        self.assertTrue(recognized)
        self.assertEqual(facility['facility_id'], '520109')

    def test_search_ambiguity_clears_previous_identity(self):
        self.assertEqual(extract_facility({'query': 'New hospital', 'count': 2,
                                         'hospitals': [{}, {}]}), (None, True))

    def test_address_facility_does_not_invent_ccn(self):
        facility, recognized = extract_facility({'target_facility': {
            'facility_name': 'Clinic', 'address': '1 Example St', 'city': 'Test',
            'state': 'WI', 'zip_code': '53900', 'address_verification': 'user_confirmed'}})
        self.assertTrue(recognized)
        self.assertNotIn('facility_id', facility)
        self.assertTrue(facility['address_verified'])

    def test_stream_forwards_history_and_emits_minimal_identity(self):
        def runner(message, callbacks, history, current_facility):
            self.assertEqual(history[0]['content'], 'earlier')
            callbacks[0].on_tool_end({'facility_name': 'New hospital', 'facility_id': '010001',
                                      'large_tool_payload': 'private'})
            return 'answer'
        events = [json.loads(line) for line in stream_agent_events('its finances', runner,
            history=[{'role': 'user', 'content': 'earlier'}],
            current_facility={'facility_name': 'Old'})]
        context = next(e for e in events if e['type'] == 'context')
        self.assertEqual(context['current_facility']['facility_id'], '010001')
        self.assertNotIn('private', json.dumps(events))


if __name__ == '__main__':
    unittest.main()
