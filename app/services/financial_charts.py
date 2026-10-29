"""Validated financial chart payloads; drawing never depends on model-generated values."""

import math

from app.services.data_quality_service import parse_fiscal_date

from app.services.cost_report_service import get_available_report_years
from app.services.agent_progress import report_progress

METRICS = {
    'operating_margin': ('Operating margin', '%'),
    'liability_to_asset_ratio': ('Liabilities / assets', '%'),
    'occupancy_rate': ('Bed occupancy', '%'),
    'cost_to_charge_ratio': ('Cost / charge', 'ratio'),
}


def _point(row, metric, year):
    """Blocked, missing and non-finite metrics stay gaps, never zero."""
    value = row.get(metric)
    if metric in row.get('blocked_metrics', []):
        value = None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        value = None
    if value is not None and not math.isfinite(value):
        value = None
    return {'year': year, 'value': value,
            'fiscal_year_begin': row.get('fiscal_year_begin'),
            'fiscal_year_end': row.get('fiscal_year_end'),
            'source_provenance': row.get('source_provenance') or row.get('data_provenance')}


def build_financial_charts(facility_ids, chart_type, financial_lookup, trend_lookup,
                           year=None, start_year=None, end_year=None):
    """Build up to four metric charts for one trend or two-to-five hospitals."""
    # Validate explicit hospital identities and bound all work.
    if chart_type not in ('line', 'bar'):
        raise ValueError('chart_type must be line or bar.')
    if not isinstance(facility_ids, list) or not 1 <= len(facility_ids) <= 5:
        raise ValueError('Provide one to five resolved hospital CCNs.')
    ids = []
    for value in facility_ids:
        if not isinstance(value, str) or not value.strip():
            raise ValueError('Hospital CCNs must be nonempty strings.')
        if value.strip().upper() in ids:
            raise ValueError('Provide distinct hospital CCNs.')
        ids.append(value.strip().upper())
    if chart_type == 'bar' and len(ids) < 2:
        raise ValueError('A comparison needs two to five hospitals.')
    for value in (year, start_year, end_year):
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int) or not 2011 <= value <= 2100:
                raise ValueError('Dataset years must be integers between 2011 and 2100.')
    if start_year is not None and end_year is not None:
        if not 0 <= end_year - start_year <= 9:
            raise ValueError('Select at most ten consecutive dataset years.')
    if chart_type == 'line' and year is not None:
        raise ValueError('Use start_year/end_year for a line chart.')
    if chart_type == 'bar' and (start_year is not None or end_year is not None):
        raise ValueError('Use year for a bar chart.')

    # Reuse validated financial tools. No access analysis or geocoding is needed.
    reports = []
    notes = ['Source: CMS Hospital Provider Cost Report. Dataset years can differ from fiscal years.',
             'Missing or blocked values are omitted, not treated as zero. Historical results do not predict closure.']
    selected_year = year
    if chart_type == 'line':
        if end_year is None:
            available = get_available_report_years()
            if not available:
                raise ValueError('No available financial dataset years.')
            end_year = max(available)
        if start_year is None:
            start_year = max(2011, end_year - 4)
        if not 0 <= end_year - start_year <= 9:
            raise ValueError('Select at most ten consecutive dataset years.')
        for ccn in ids:
            report_progress(f'Preparing financial trend chart for {ccn}…')
            reports.append(trend_lookup(ccn, start_year=start_year, end_year=end_year))
    else:
        years = []
        if year is not None:
            years.append(year)
        else:
            years = sorted(get_available_report_years(), reverse=True)
        # A common dataset year is required; never mix each hospital's latest year.
        for candidate in years:
            candidate_reports = []
            complete = True
            for ccn in ids:
                report_progress(f'Checking chart report year {candidate} for {ccn}…')
                report = financial_lookup(ccn, year=candidate)
                candidate_reports.append(report)
                if report.get('error') or report.get('report_year') != candidate:
                    complete = False
            if complete:
                reports = candidate_reports
                selected_year = candidate
                break
        if not reports:
            return {'charts': [], 'error': 'No common financial dataset year was retrieved for all hospitals.'}

    # Fiscal misalignment disables comparative bars; retain labeled source tables.
    periods = []
    plot_allowed = True
    if chart_type == 'bar':
        for report in reports:
            try:
                begin = parse_fiscal_date(report.get('fiscal_year_begin'))
                end = parse_fiscal_date(report.get('fiscal_year_end'))
                periods.append((begin, end))
                if not 330 <= (end - begin).days + 1 <= 400:
                    plot_allowed = False
            except ValueError:
                periods.append((None, None))
                plot_allowed = False
            for alert in report.get('indicators', {}).get('quality_warnings', []):
                if alert.get('code') == 'fiscal_period_review':
                    plot_allowed = False
        for period in periods:
            if not period[0] or not period[1] or period != periods[0]:
                plot_allowed = False
        if not plot_allowed:
            notes.append('Fiscal periods differ or require review. Comparative bars are withheld; see the reported values and periods below.')
        if year is None:
            notes.append('Selected the latest successfully retrieved common dataset year; this is not a live source freshness check.')

    charts = []
    for metric, (label, unit) in METRICS.items():
        series = []
        for index, report in enumerate(reports):
            if report.get('error'):
                notes.append(ids[index] + ': ' + str(report['error']))
                continue
            points = []
            connect = True
            name = report.get('hospital_name')
            if chart_type == 'line':
                by_year = {}
                for row in report.get('yearly_indicators', []):
                    by_year[row['report_year']] = row
                for requested_year in report.get('years_requested', []):
                    points.append(_point(by_year.get(requested_year, {}), metric, requested_year))
                for alert in report.get('quality_warnings', []):
                    if alert.get('code') in ('trend_fiscal_periods', 'fiscal_period_review'):
                        connect = False
                if not connect:
                    notes.append(ids[index] + ': fiscal periods require review; points are shown without connecting lines.')
            else:
                row = report.get('indicators', {})
                name = row.get('hospital_name')
                points.append(_point(row, metric, selected_year))
            if not name:
                name = ids[index]
            series.append({'facility_id': ids[index], 'name': name,
                           'connect': connect, 'points': points})
        if not series:
            continue
        charts.append({'id': chart_type + ':' + metric + ':' + ','.join(ids),
                       'type': chart_type, 'metric': metric, 'title': label,
                       'unit': unit, 'series': series, 'plot_allowed': plot_allowed,
                       'source_url': 'https://www.cms.gov/data-research/statistics-trends-and-reports/cost-reports'})
    unique_notes = []
    for note in notes:
        if note not in unique_notes:
            unique_notes.append(note)
    return {'charts': charts, 'notes': unique_notes,
            'report_year': selected_year, 'chart_type': chart_type}
