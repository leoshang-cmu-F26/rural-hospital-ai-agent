"""Compose existing deterministic analyses, preserving partial evidence."""
import logging
import sqlite3
import requests
from app.services.cms_service import get_hospital_by_id
from app.services.cost_report_service import CostReportUnavailableError
from app.services.agent_progress import report_progress

logger = logging.getLogger(__name__)


def _section(lookup, **kwargs):
    # Normalize retrieval failures without discarding the other report sections.
    try:
        data = lookup(**kwargs)
        if data is None:
            return {'available': False, 'error': 'No matching data found.'}
        if 'error' in data:
            return {**data, 'available': False}
        return {**data, 'available': True}
    except (requests.RequestException, CostReportUnavailableError, ValueError, sqlite3.Error) as error:
        logger.warning('Investigation section unavailable: %s', type(error).__name__)
        return {'available': False, 'error': 'This data section could not be retrieved. Please retry later.'}


def build_hospital_investigation(facility_id, financial_lookup, trend_lookup,
                                 access_lookup, start_year=None, end_year=None):
    """No scores or predictions; reuse the existing tools' values and periods."""
    # 1. Validate identity and trend bounds before external data requests.
    facility_id = facility_id.strip()
    if not facility_id:
        return {'error': 'A hospital CCN is required.'}
    if start_year is not None and end_year is not None and start_year > end_year:
        return {'error': 'start_year must not exceed end_year.'}
    # 2. Resolve the target once; never substitute another hospital.
    report_progress('Identifying the hospital for a full investigation…')
    try:
        hospital = get_hospital_by_id(facility_id)
    except requests.RequestException:
        return {'error': 'CMS hospital information could not be retrieved.', 'facility_id': facility_id}
    if hospital is None:
        return {'error': 'Hospital not found in the current CMS hospital dataset.', 'facility_id': facility_id}

    # 3. Retrieve latest financials separately from the requested trend period.
    report_progress('Retrieving the latest financial report and indicators…')
    financials = _section(financial_lookup, facility_id=facility_id)
    # 4. Summarize the available multi-year history with its actual year coverage.
    report_progress('Reviewing multi-year financial trends…')
    trend = _section(trend_lookup, facility_id=facility_id,
                     start_year=start_year, end_year=end_year)
    # 5. Gather administrative, demographic, shortage and distance evidence.
    report_progress('Gathering hospital alternatives, population and shortage evidence…')
    access = _section(access_lookup, facility_id=facility_id)
    # 6. Record section-level and nested gaps without changing numeric values.
    sections = {'financials': financials, 'financial_trend': trend, 'healthcare_access': access}
    gaps = []
    for name, section in sections.items():
        if not section['available']:
            gaps.append({'section': name, 'reason': section.get('error', 'Unavailable')})
    if financials.get('available'):
        fields = financials.get('indicators', {}).get('missing_fields', [])
        if fields:
            gaps.append({'section': 'financials', 'missing_fields': fields})
    if trend.get('available'):
        for key in ('years_without_report', 'years_unavailable'):
            if trend.get(key):
                gaps.append({'section': 'financial_trend', key: trend[key]})
    if access.get('available'):
        if access.get('county_comparison_available') is False:
            gaps.append({'section': 'county_comparison',
                         'reason': access.get('county_comparison_error', 'County unavailable')})
        for key in ('county_demographics', 'primary_care_hpsa', 'distance_analysis'):
            item = access.get(key)
            if not item or not item.get('available'):
                gaps.append({'section': key, 'reason': (item or {}).get('error', 'Unavailable')})
        skipped = access.get('distance_analysis', {}).get('skipped_geocoding_count', 0)
        if skipped:
            gaps.append({'section': 'distance_analysis', 'excluded_hospital_count': skipped})
    # 7. Partial means incomplete evidence, not a hospital risk classification.
    if gaps:
        status = 'partial'
    else:
        status = 'complete'

    return {
        'target_hospital': hospital.model_dump(),
        **sections,
        'data_gaps': gaps,
        'status': status,
        'notes': [
            'Financials use the latest available single-year report; trends use the requested period or the default recent five dataset years.',
            'Use actual report years and fiscal periods; do not imply different periods are directly comparable.',
            'This report does not calculate a risk score or predict closure, bankruptcy or recovery.',
            'County and distance evidence does not establish equivalent services, capacity or patient eligibility.',
        ],
    }
