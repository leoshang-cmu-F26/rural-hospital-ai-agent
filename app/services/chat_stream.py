"""Stream progress and a final answer from a synchronous agent run."""
import json
import logging
from queue import Queue, Empty
from threading import Event, Thread

from app.services.agent_progress import _sink, ToolProgressHandler

logger = logging.getLogger(__name__)


def stream_agent_events(message, runner, history=None, current_facility=None, comparison_facilities=None):
    """Bridge a synchronous worker to newline-delimited events with request isolation."""
    # 1. Keep each chat request in its own queue and disconnect flag.
    events = Queue()
    stopped = Event()

    # Stop buffering events after the client disconnects.
    def emit(event):
        if not stopped.is_set():
            events.put(event)

    # 2. Run blocking model/tool work outside the response iterator.
    def run():
        # Bind service progress only to this worker and always restore the context.
        token = _sink.set(emit)
        try:
            # Forward optional context without changing legacy runner call contracts.
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

    # 3. Send an initial state immediately, before external requests can block.
    yield json.dumps({'type': 'progress', 'message': 'Understanding your request…'}) + '\n'
    Thread(target=run, daemon=True, name='agent-chat-stream').start()
    try:
        # 4. Send events in order; heartbeat frames keep an idle connection alive.
        while True:
            try:
                event = events.get(timeout=10)
            except Empty:
                event = {'type': 'heartbeat'}
            if event is None:
                break
            yield json.dumps(event, ensure_ascii=False) + '\n'
    finally:
        # Stop delivery; this does not cancel an external request already running.
        stopped.set()
