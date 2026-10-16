"""Stream progress and a final answer from a synchronous agent run."""
import json
import logging
from queue import Queue, Empty
from threading import Event, Thread

from app.services.agent_progress import _sink, ToolProgressHandler

logger = logging.getLogger(__name__)


def stream_agent_events(message, runner, history=None, current_facility=None, comparison_facilities=None):
    events = Queue()
    stopped = Event()

    def emit(event):
        if not stopped.is_set():
            events.put(event)

    def run():
        token = _sink.set(emit)
        try:
            options = {"callbacks": [ToolProgressHandler(emit)]}
            if history is not None:
                options["history"] = history
            if current_facility is not None:
                options["current_facility"] = current_facility
            if comparison_facilities:
                options["comparison_facilities"] = comparison_facilities
            answer = runner(message, **options)
            if not answer:
                raise ValueError('Empty agent response')
            emit({'type': 'result', 'response': answer})
        except Exception:
            logger.exception('Streaming agent request failed')
            emit({'type': 'error', 'message': 'The agent could not complete this request. Please try again.'})
        finally:
            _sink.reset(token)
            emit(None)

    yield json.dumps({'type': 'progress', 'message': 'Understanding your request…'}) + '\n'
    Thread(target=run, daemon=True, name='agent-chat-stream').start()
    try:
        while True:
            try:
                event = events.get(timeout=10)
            except Empty:
                event = {'type': 'heartbeat'}
            if event is None:
                break
            yield json.dumps(event, ensure_ascii=False) + '\n'
    finally:
        stopped.set()
