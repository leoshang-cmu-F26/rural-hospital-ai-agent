"""Offline rules for actionable notices, rural reminders and reliable comparisons."""
import json
from types import SimpleNamespace
from unittest.mock import patch

from app.models.financial import HospitalFinancialRecord, FinancialIndicators
from app.services.data_quality_service import collect_quality_warnings, add_rural_context, rural_from_record
from app.services.agent_progress import ToolProgressHandler
from app.tools.financial_tools import calculate_financial_indicators
from app.tools.trend_tools import build_financial_trend


def record(**overrides):
    fields = dict(facility_id='001', hospital_name='Example', report_year=2024,
                  fiscal_year_begin='2024-01-01', fiscal_year_end='2024-12-31',
                  rural_versus_urban='R', net_patient_revenue=100, net_income_from_service=-5,
                  total_assets=100, total_liabilities=80, total_days=50,
                  total_bed_days_available=100, cost_to_charge_ratio=0.3)
    fields.update(overrides)
    return HospitalFinancialRecord(**fields)


def test_negative_assets_ratio_is_traceable_but_not_interpretable():
    result = calculate_financial_indicators(record(total_assets=-100))
    assert result.liability_to_asset_ratio == -80
    assert 'liability_to_asset_ratio' in result.blocked_metrics
    assert any(item['code'] == 'invalid_denominator' for item in result.quality_warnings)


def test_zero_denominator_missing_input_and_nonfinite_are_distinct():
    result = calculate_financial_indicators(record(total_assets=0, total_days=None))
    assert result.liability_to_asset_ratio is None
    assert 'total_assets' not in result.missing_fields
    assert 'total_days' in result.missing_fields
    finite = calculate_financial_indicators(record(total_assets=float('nan'), cost_to_charge_ratio=float('inf')))
    json.dumps(finite.model_dump(), allow_nan=False)
    assert finite.liability_to_asset_ratio is None
    assert finite.cost_to_charge_ratio is None


def test_nonannual_fiscal_period_has_actionable_warning():
    result = calculate_financial_indicators(record(fiscal_year_end='2024-05-01'))
    assert any(item['code'] == 'fiscal_period_review' and item['action'] for item in result.quality_warnings)


def test_urban_classification_is_dated_and_not_a_refusal():
    classification, alerts = rural_from_record(record(rural_versus_urban='U'))
    assert classification['status'] == 'urban'
    assert classification['report_year'] == 2024
    assert alerts[0]['code'] == 'non_rural_hospital'
    assert 'continue' in alerts[0]['action'].lower()


def test_unknown_classification_never_becomes_urban():
    for item in (None, record(rural_versus_urban='?')):
        classification, alerts = rural_from_record(item)
        assert classification['status'] == 'unknown'
        assert alerts[0]['code'] == 'rural_status_unknown'


def test_classification_outage_preserves_successful_identity():
    def fail(*args, **kwargs):
        raise ValueError('private upstream detail')
    result = add_rural_context({'resolution_status': 'resolved_hospital'}, '001', fail)
    assert result['resolution_status'] == 'resolved_hospital'
    assert result['rural_classification']['status'] == 'unknown'
    assert 'private upstream detail' not in str(result)


def test_named_hospital_resolver_adds_nonrural_notice_without_extra_model_call():
    from app.tools.agent_tools import resolve_facility
    resolved = {'resolution_status': 'resolved_hospital', 'target_hospital': {'facility_id': '001'}}
    with patch('app.services.facility_resolution_service.resolve_facility_identity', return_value=resolved), \
         patch('app.tools.agent_tools.get_financial_data_by_hospital', return_value=record(rural_versus_urban='U')):
        result = resolve_facility.invoke({'name': 'Example', 'state': 'WI'})
    assert result['quality_warnings'][0]['code'] == 'non_rural_hospital'
    assert result['target_hospital']['facility_id'] == '001'


def test_access_only_known_ccn_also_adds_nonrural_notice():
    from app.tools.agent_tools import analyze_healthcare_access
    with patch('app.tools.agent_tools.get_healthcare_access_analysis', return_value={'facility_id': '001'}), \
         patch('app.tools.agent_tools.get_financial_data_by_hospital', return_value=record(rural_versus_urban='U')):
        result = analyze_healthcare_access.invoke({'facility_id': '001'})
    assert result['rural_classification']['status'] == 'urban'


def test_mixed_trend_is_not_a_simple_improvement_label():
    yearly = []
    for year, margin in ((2022, -5), (2023, 5), (2024, -2)):
        yearly.append(FinancialIndicators(facility_id='001', hospital_name='Example', report_year=year, operating_margin=margin,
            fiscal_year_begin=f'{year}-01-01', fiscal_year_end=f'{year}-12-31'))
    trend = build_financial_trend('001', yearly, [2022, 2023, 2024], [], {})
    assert trend.indicator_trends['operating_margin'].direction == 'mixed'
    assert trend.indicator_trends['operating_margin'].change == 3
    assert any(item['code'] == 'trend_reversals' for item in trend.quality_warnings)


def test_overlapping_fiscal_periods_withhold_direction():
    yearly = []
    for year, margin in ((2023, -5), (2024, 5)):
        yearly.append(FinancialIndicators(facility_id='001', hospital_name='Example', report_year=year, operating_margin=margin,
            fiscal_year_begin='2023-01-01', fiscal_year_end='2023-12-31'))
    trend = build_financial_trend('001', yearly, [2023, 2024], [], {})
    assert trend.indicator_trends['operating_margin'].direction == 'requires_review'
    assert trend.indicator_trends['operating_margin'].change is None


def test_bad_ratio_does_not_create_a_directional_trend():
    yearly = []
    for year, assets in ((2023, 100), (2024, -100)):
        yearly.append(calculate_financial_indicators(record(report_year=year, total_assets=assets,
            fiscal_year_begin=f'{year}-01-01', fiscal_year_end=f'{year}-12-31')))
    trend = build_financial_trend('001', yearly, [2023, 2024], [], {})
    assert trend.indicator_trends['liability_to_asset_ratio'].direction == 'requires_review'


def test_missing_evidence_emits_model_independent_warning_frames():
    events = []
    handler = ToolProgressHandler(events.append)
    handler.on_tool_end({'facility_id': '001', 'county_demographics': {'available': False},
                         'distance_analysis': {'available': True, 'skipped_geocoding_count': 2}})
    codes = set()
    for event in events:
        if event['type'] == 'warnings':
            for alert in event['warnings']:
                codes.add(alert['code'])
    assert 'unavailable_county_demographics' in codes
    assert 'excluded_coordinates' in codes


def test_comparison_alignment_notice_and_nested_warning_deduplication():
    alert = {'code': 'non_rural_hospital', 'message': 'Urban', 'action': 'Continue', 'report_year': 2024}
    result = collect_quality_warnings({'financial_alignment': {'fiscal_periods_match': False},
        'hospital_reports': [{'target_hospital': {'facility_id': '001', 'facility_name': 'Example'},
            'financials': {'quality_warnings': [alert, alert]}}]})
    assert len(result) == 2
    assert result[1]['facility_name'] == 'Example'


def test_invalid_comparison_metric_difference_is_withheld():
    from app.services.comparison_service import compare_hospitals
    def financial(facility_id, year=None):
        return {'report_year': 2024, 'fiscal_year_begin': '2024-01-01', 'fiscal_year_end': '2024-12-31',
                'indicators': {'liability_to_asset_ratio': -80, 'operating_margin': 5,
                               'blocked_metrics': ['liability_to_asset_ratio']}}
    hospital = SimpleNamespace(facility_id='001', model_dump=lambda: {'facility_id': '001', 'facility_name': 'Example'})
    other = SimpleNamespace(facility_id='002', model_dump=lambda: {'facility_id': '002', 'facility_name': 'Other'})
    with patch('app.services.comparison_service.get_hospital_by_id', side_effect=[hospital, other]):
        result = compare_hospitals('001', '002', financial, lambda **k: {}, lambda **k: {}, year=2024)
    assert not any(item['metric'] == 'liability_to_asset_ratio' for item in result['financial_differences'])
    assert any(item['metric'] == 'operating_margin' for item in result['financial_differences'])



def test_missing_year_breaks_consecutive_loss_claim():
    yearly = []
    for year in (2022, 2024):
        yearly.append(FinancialIndicators(facility_id='001', hospital_name='Example', report_year=year, operating_margin=-5,
            fiscal_year_begin=f'{year}-01-01', fiscal_year_end=f'{year}-12-31'))
    trend = build_financial_trend('001', yearly, [2022, 2023, 2024], [2023], {})
    assert trend.consecutive_negative_operating_margin_years == 1
    assert any(item['code'] == 'trend_year_gaps' for item in trend.quality_warnings)
