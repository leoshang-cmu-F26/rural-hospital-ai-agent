from app.services.evidence_summary import evidence_summary
"""Request-local, public progress events; never expose model reasoning."""
from contextvars import ContextVar
from app.services.chat_context import extract_facility, extract_comparison
from langchain_core.callbacks import BaseCallbackHandler

_sink = ContextVar('agent_progress_sink', default=None)


def report_progress(message):
    sink = _sink.get()
    if sink is not None:
        sink({'type': 'progress', 'message': message})


class ToolProgressHandler(BaseCallbackHandler):
    def __init__(self, sink):
        self.sink = sink

    def on_tool_start(self, serialized, input_str, **kwargs):
        messages = {
            'compare_hospital_investigations': 'Aligning reports and comparing both hospitals…',
            'investigate_hospital': 'Building a full hospital investigation…',
            'search_hospital': 'Searching CMS hospital records…',
            'get_hospital_by_ccn': 'Looking up hospital information…',
            'analyze_hospital_financials': 'Retrieving CMS financial data and indicators…',
            'analyze_financial_trend': 'Retrieving reports and analyzing financial trends…',
            'compare_hospitals_by_area': 'Finding hospitals in the requested area…',
            'analyze_healthcare_access': 'Gathering healthcare-access evidence…',
            'analyze_facility_access_by_address': 'Resolving the supplied facility address…',
            'get_hospital_demographics': 'Querying county population estimates…',
        }
        self.sink({'type': 'progress', 'message': messages.get(
            (serialized or {}).get('name'), 'Retrieving evidence…')})

    def on_tool_end(self, output, **kwargs):
        evidence = evidence_summary(output)
        if evidence:
            self.sink({'type': 'evidence', 'sections': evidence})
        pair = extract_comparison(output)
        if pair:
            self.sink({'type': 'comparison_context', 'comparison_facilities': pair})
        facility, recognized = extract_facility(output)
        if recognized:
            self.sink({'type': 'context', 'current_facility': facility})
        self.sink({'type': 'progress', 'message': 'Reviewing results and preparing the next step…'})

    def on_tool_error(self, error, **kwargs):
        self.sink({'type': 'progress', 'message': 'A data lookup failed; checking whether analysis can continue…'})
