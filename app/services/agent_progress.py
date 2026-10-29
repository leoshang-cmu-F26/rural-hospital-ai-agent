"""Request-local, public progress events; never expose model reasoning."""

import json

from contextvars import ContextVar
from app.services.chat_context import extract_facility, extract_comparison
from langchain_core.callbacks import BaseCallbackHandler
from app.services.evidence_summary import evidence_summary
from app.services.data_quality_service import collect_quality_warnings

# One sink per execution context avoids mixing concurrent conversations.
_sink = ContextVar('agent_progress_sink', default=None)


def report_progress(message):
    """Publish a service activity only when the current request has a progress sink."""
    sink = _sink.get()
    if sink is not None:
        sink({'type': 'progress', 'message': message})


class ToolProgressHandler(BaseCallbackHandler):
    """Publish public tool activity, evidence and interpretation notices."""

    def __init__(self, sink):
        self.sink = sink

    def on_tool_start(self, serialized, input_str, **kwargs):
        # Publish readable activity names, never model reasoning or raw inputs.
        messages = {
            'create_financial_chart': 'Preparing validated financial charts…',
            'list_rural_hospitals': 'Listing CMS-classified rural hospitals…',
            'get_county_health_context': 'Reading county statistical evidence…',
            'search_methodology_documents': 'Searching official methodology documents…',
            'analyze_area_healthcare_access': 'Analyzing healthcare access across the requested area…',
            'resolve_facility': 'Checking facility identity and current CMS records…',
            'search_tribal_facility_directory': 'Searching the historical CMS/IHS tribal facility directory…',
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
        self.sink(
            {
                'type': 'progress',
                'message': messages.get((serialized or {}).get('name'), 'Retrieving evidence…'),
            }
        )

    def on_tool_end(self, output, **kwargs):
        # Tool completion can update evidence cards and the active identity/pair.
        chart_data = output
        if hasattr(chart_data, 'content'):
            chart_data = chart_data.content
        if isinstance(chart_data, str):
            try:
                chart_data = json.loads(chart_data)
            except (ValueError, TypeError):
                chart_data = None
        if isinstance(chart_data, dict) and chart_data.get('charts'):
            self.sink({'type': 'charts', 'charts': chart_data['charts'],
                       'notes': chart_data.get('notes', [])})
            # Do not leave the last resolved hospital active after a multi-target chart.
            targets = []
            for series in chart_data['charts'][0].get('series', []):
                targets.append({'facility_id': series['facility_id'],
                                'facility_name': series['name']})
            if len(targets) == 1:
                self.sink({'type': 'context', 'current_facility': targets[0]})
            elif len(targets) == 2:
                self.sink({'type': 'comparison_context', 'comparison_facilities': targets})
            else:
                self.sink({'type': 'context', 'current_facility': None})
        warnings = collect_quality_warnings(output)
        if warnings:
            self.sink({'type': 'warnings', 'warnings': warnings})
        evidence = evidence_summary(output)
        if evidence:
            self.sink({'type': 'evidence', 'sections': evidence})
        pair = extract_comparison(output)
        if pair:
            self.sink({'type': 'comparison_context', 'comparison_facilities': pair})
        # A recognized empty identity deliberately clears a stale target.
        facility, recognized = extract_facility(output)
        if recognized:
            self.sink({'type': 'context', 'current_facility': facility})
        self.sink({'type': 'progress', 'message': 'Reviewing results and preparing the next step…'})

    def on_tool_error(self, error, **kwargs):
        self.sink(
            {
                'type': 'progress',
                'message': 'A data lookup failed; checking whether analysis can continue…',
            }
        )
