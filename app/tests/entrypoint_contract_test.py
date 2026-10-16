"""Exercise actual route/runner call contracts without initializing a real model."""
import ast
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from fastapi import HTTPException
from app.agents.agent import AgentRequest, AgentResponse
from app.services.chat_context import build_messages
from app.services.chat_stream import stream_agent_events


class EntrypointContractTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse(Path('app/agents/hospital_agent.py').read_text(encoding='utf-8'))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'ask_hospital_agent')
        self.agent = Mock()
        self.agent.invoke.return_value = {'messages': [type('Answer', (), {'text': 'financial answer'})()]}
        self.namespace = {'hospital_agent': self.agent, 'build_messages': build_messages}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), '<runner>', 'exec'), self.namespace)
        self.runner = self.namespace['ask_hospital_agent']
        self.request = AgentRequest(message='Analyze its financial distress.',
            history=[{'role':'assistant', 'content':'Mile Bluff Medical Center, CCN 520109'}],
            current_facility={'facility_name':'Mile Bluff Medical Center', 'facility_id':'520109'})

    def test_non_stream_route_passes_context_to_real_runner(self):
        tree = ast.parse(Path('app/api/routes.py').read_text(encoding='utf-8'))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'chat_with_agent')
        fn.decorator_list = []
        namespace = {'AgentRequest':AgentRequest, 'AgentResponse':AgentResponse,
                     'ask_hospital_agent':self.runner, 'HTTPException':HTTPException,
                     'logger':Mock()}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), '<route>', 'exec'), namespace)
        self.assertEqual(namespace['chat_with_agent'](self.request).response, 'financial answer')
        self.assertIn('520109', self.agent.invoke.call_args.args[0]['messages'][0]['content'])

    def test_stream_passes_context_and_callbacks_to_real_runner(self):
        events = [json.loads(line) for line in stream_agent_events(self.request.message,
            self.runner, history=self.request.history, current_facility=self.request.current_facility)]
        self.assertEqual(events[-1]['type'], 'result')
        self.assertEqual(events[-1]['response'], 'financial answer')
        self.assertTrue(self.agent.invoke.call_args.kwargs['config']['callbacks'])
        self.assertIn('520109', self.agent.invoke.call_args.args[0]['messages'][0]['content'])

    def test_old_single_message_caller_still_works(self):
        self.assertEqual(self.runner('hello'), 'financial answer')


if __name__ == '__main__':
    unittest.main()
