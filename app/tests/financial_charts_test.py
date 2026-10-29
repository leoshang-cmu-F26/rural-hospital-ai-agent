"""Financial chart boundaries, missing values, alignment and stream delivery."""

import json
from unittest.mock import Mock

import pytest

from app.services.financial_charts import build_financial_charts
from app.services.agent_progress import ToolProgressHandler


def financial(ccn, year=2024, begin='2024-01-01'):
    return {'report_year': year, 'fiscal_year_begin': begin, 'fiscal_year_end': '2024-12-31',
            'indicators': {'hospital_name': 'Hospital ' + ccn, 'operating_margin': -12,
                           'occupancy_rate': 0, 'liability_to_asset_ratio': 40,
                           'cost_to_charge_ratio': 0.2, 'blocked_metrics': []}}


def test_line_keeps_missing_years_and_blocks_invalid_metrics():
    trend = {'hospital_name': 'Test', 'years_requested': [2022, 2023, 2024],
             'yearly_indicators': [{'report_year': 2022, 'operating_margin': -12},
                                   {'report_year': 2024, 'operating_margin': 9,
                                    'blocked_metrics': ['operating_margin']}],
             'quality_warnings': [{'code': 'trend_fiscal_periods'}]}
    result = build_financial_charts(['520109'], 'line', Mock(), Mock(return_value=trend),
                                    start_year=2022, end_year=2024)
    series = result['charts'][0]['series'][0]
    assert series['points'][0]['value'] == -12
    assert series['points'][1]['value'] is None
    assert series['points'][2]['value'] is None
    assert series['connect'] is False


def test_three_hospital_bars_and_zero_values():
    result = build_financial_charts(['1', '2', '3'], 'bar',
                                    lambda ccn, year: financial(ccn, year), Mock(), year=2024)
    assert len(result['charts']) == 4
    assert len(result['charts'][0]['series']) == 3
    assert result['charts'][0]['plot_allowed']
    assert result['charts'][2]['series'][0]['points'][0]['value'] == 0


def test_fiscal_mismatch_withholds_bars_but_keeps_tables():
    def lookup(ccn, year):
        if ccn == '2':
            return financial(ccn, year, '2024-02-01')
        return financial(ccn, year)
    result = build_financial_charts(['1', '2'], 'bar', lookup, Mock(), year=2024)
    assert result['charts'][0]['plot_allowed'] is False
    assert result['charts'][0]['series'][0]['points'][0]['value'] == -12


def test_default_common_year_does_not_mix_hospital_latest(monkeypatch):
    monkeypatch.setattr('app.services.financial_charts.get_available_report_years', lambda: [2023, 2024])
    def lookup(ccn, year):
        if year == 2024 and ccn == '2':
            return {'error': 'Not found'}
        return financial(ccn, year)
    result = build_financial_charts(['1', '2'], 'bar', lookup, Mock())
    assert result['report_year'] == 2023
    for series in result['charts'][0]['series']:
        assert series['points'][0]['year'] == 2023


@pytest.mark.parametrize('ids,kind,options', [([], 'line', {}), (['1', '1'], 'bar', {}),
    (['1'], 'bar', {}), (['1'], 'pie', {}), (['1'], 'line', {'start_year': 2011, 'end_year': 2024}),
    (['1'], 'bar', {'year': True}), (['1'], 'line', {'year': 2024})])
def test_invalid_requests(ids, kind, options):
    with pytest.raises(ValueError):
        build_financial_charts(ids, kind, Mock(), Mock(), **options)


def test_chart_payload_streams_from_tool_output():
    events = []
    handler = ToolProgressHandler(events.append)
    handler.on_tool_end(json.dumps({'charts': [{'id': 'test'}], 'notes': ['CMS']}))
    assert events[0] == {'type': 'charts', 'charts': [{'id': 'test'}], 'notes': ['CMS']}


def test_cms_csv_dates_are_valid_annual_reports():
    from app.models.financial import HospitalFinancialRecord
    from app.services.data_quality_service import financial_quality, parse_fiscal_date
    record = HospitalFinancialRecord(facility_id='1', hospital_name='Test',
        fiscal_year_begin='10/01/2023', fiscal_year_end='09/30/2024',
        net_patient_revenue=100, total_assets=100, total_bed_days_available=100)
    alerts, blocked = financial_quality(record)
    for alert in alerts:
        assert alert['code'] != 'fiscal_period_review'
    assert parse_fiscal_date('10/01/2023') == parse_fiscal_date('2023-10-01T00:00:00Z')


def test_bar_accepts_equivalent_cms_csv_and_iso_dates():
    def lookup(ccn, year):
        report = financial(ccn, year)
        if ccn == '2':
            report['fiscal_year_begin'] = '01/01/2024'
            report['fiscal_year_end'] = '12/31/2024'
        return report
    result = build_financial_charts(['1', '2'], 'bar', lookup, Mock(), year=2024)
    assert result['charts'][0]['plot_allowed']
