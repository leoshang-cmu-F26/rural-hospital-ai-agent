"""Data-quality rules and dated rural notices, separate from hospital risk labels."""

from datetime import datetime
import json
import math

# Structured interpretation notices


def warning(code, message, action, metric=None, severity='warning', **context):
    """Use stable codes for frontend deduplication and regression checks."""
    warning_fields = {}
    warning_fields['code'] = code
    warning_fields['severity'] = severity
    warning_fields['metric'] = metric
    warning_fields['message'] = message
    warning_fields['action'] = action
    for copied_key, copied_value in (context).items():
        warning_fields[copied_key] = copied_value

    return warning_fields


# Financial source validation


def financial_quality(record):
    """Preserve reported values while blocking misleading ratio interpretation."""
    alerts = []
    blocked = []
    # 1. Positive denominators are required for conventional ratio interpretation.
    for metric, field in (
        ('operating_margin', 'net_patient_revenue'),
        ('occupancy_rate', 'total_bed_days_available'),
        ('liability_to_asset_ratio', 'total_assets'),
    ):
        value = getattr(record, field)
        if value is None or not math.isfinite(value) or value <= 0:
            blocked.append(metric)
            alerts.append(
                warning(
                    'invalid_denominator',
                    f'{field} is missing, non-finite, zero or negative; {metric} cannot be interpreted conventionally.',
                    'Inspect the original cost report. Do not rank this metric, infer improvement, or use it in direct differences.',
                    metric=metric,
                    field=field,
                    report_year=record.report_year,
                )
            )
    # 2. Flag impossible utilization and non-finite source inputs independently.
    if record.total_days is not None and record.total_bed_days_available is not None:
        if record.total_days < 0 or record.total_days > record.total_bed_days_available:
            if 'occupancy_rate' not in blocked:
                blocked.append('occupancy_rate')
            alerts.append(
                warning(
                    'invalid_utilization',
                    'Reported patient days are negative or exceed available bed days.',
                    'Verify scope and source fields before interpreting occupancy.',
                    metric='occupancy_rate',
                    report_year=record.report_year,
                )
            )
    for metric, field in (
        ('operating_margin', 'net_income_from_service'),
        ('liability_to_asset_ratio', 'total_liabilities'),
        ('occupancy_rate', 'total_days'),
        ('cost_to_charge_ratio', 'cost_to_charge_ratio'),
    ):
        value = getattr(record, field)
        invalid = value is not None and not math.isfinite(value)
        if (
            metric in ('liability_to_asset_ratio', 'cost_to_charge_ratio')
            and value is not None
            and value < 0
        ):
            invalid = True
        if invalid:
            if metric not in blocked:
                blocked.append(metric)
            alerts.append(
                warning(
                    'invalid_source_value',
                    f'{field} is non-finite or outside its conventional nonnegative range.',
                    'Inspect the reported source field before interpreting this indicator.',
                    metric=metric,
                    report_year=record.report_year,
                )
            )
    # 3. Actual fiscal dates matter; a dataset year is not the fiscal period.
    try:
        begin = datetime.fromisoformat(record.fiscal_year_begin.replace('Z', '+00:00'))
        end = datetime.fromisoformat(record.fiscal_year_end.replace('Z', '+00:00'))
        days = (end - begin).days + 1
        if not 330 <= days <= 400:
            raise ValueError('Nonannual period')
    except (ValueError, TypeError, AttributeError):
        alerts.append(
            warning(
                'fiscal_period_review',
                'Fiscal dates are missing, invalid or do not describe an approximately annual report.',
                'Review report dates; do not assume this period is comparable to a full fiscal year.',
                report_year=record.report_year,
            )
        )
    return alerts, blocked


# Dated rural classification


def rural_from_record(record, reason=None):
    """Unknown stays unknown; an urban notice is dated and is not a refusal to analyze."""
    code = None
    year = None
    begin = None
    end = None
    if record is not None:
        code = (record.rural_versus_urban or '').strip().upper()
        year = record.report_year
        begin = record.fiscal_year_begin
        end = record.fiscal_year_end
    status = 'unknown'
    if code == 'R':
        status = 'rural'
    elif code == 'U':
        status = 'urban'
    result = {
        'status': status,
        'code': code,
        'report_year': year,
        'fiscal_year_begin': begin,
        'fiscal_year_end': end,
        'source': 'CMS Hospital Provider Cost Report: Rural Versus Urban',
        'note': 'A dated cost-report classification, not proof of current geographic rural status.',
    }
    if reason:
        result['reason'] = reason
    alerts = []
    if status == 'urban':
        year_label = 'unknown'
        if year is not None:
            year_label = str(year)
        alerts.append(
            warning(
                'non_rural_hospital',
                f'CMS classifies this hospital as urban, not rural, in cost-report dataset year {year_label}.',
                'Analysis may continue, but do not describe it as a rural hospital. Classification may differ in other years or definitions.',
                report_year=year,
            )
        )
    elif status == 'unknown':
        alerts.append(
            warning(
                'rural_status_unknown',
                'Rural/urban classification could not be established from the retrieved cost report.',
                'Do not describe the hospital as either rural or urban without evidence.',
                severity='info',
            )
        )
    return result, alerts


def add_rural_context(result, facility_id, lookup):
    """A classification-source failure must not discard an otherwise valid identity/access result."""
    if not isinstance(result, dict) or 'error' in result:
        return result
    record = None
    reason = None
    try:
        record = lookup(facility_id, year=None)
    except Exception:
        reason = 'Cost-report classification source unavailable.'
    classification, alerts = rural_from_record(record, reason)
    context_result = {}
    for copied_key, copied_value in (result).items():
        context_result[copied_key] = copied_value
    context_result['rural_classification'] = classification
    context_result['quality_warnings'] = result.get('quality_warnings', []) + alerts

    return context_result


# Frontend notice aggregation


def collect_quality_warnings(output):
    """Normalize model-independent UI notices without scanning neighboring identities."""
    raw = getattr(output, 'content', output)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    if not isinstance(raw, dict):
        return []
    result = []
    seen = set()

    def visit(data, facility_id=None, label=None):
        if not isinstance(data, dict):
            return
        target = data.get('target_hospital', {})
        facility_id = target.get('facility_id') or data.get('facility_id') or facility_id
        label = (
            target.get('facility_name')
            or data.get('hospital_name')
            or data.get('facility_name')
            or label
        )
        alerts = list(data.get('quality_warnings', []))
        # Independent access gaps become visible even when the model omits them.
        for field, evidence_label in (
            ('county_demographics', 'Census county demographics'),
            ('primary_care_hpsa', 'HRSA shortage evidence'),
            ('distance_analysis', 'Hospital distance evidence'),
        ):
            if field in data and not data[field].get('available'):
                alerts.append(
                    warning(
                        'unavailable_' + field,
                        evidence_label + ' is unavailable.',
                        'Use the other evidence only; do not treat missing data as zero or a favorable finding. Retry or verify the source.',
                    )
                )
        if data.get('county_demographics', {}).get('available'):
            alerts.append(
                warning(
                    'acs_uncertainty',
                    'County ACS values are survey estimates; this analysis does not retrieve margins of error.',
                    'Do not claim statistical differences or treat county values as the hospital service-area population.',
                    severity='info',
                )
            )
        distance = data.get('distance_analysis', {})
        skipped = distance.get('skipped_geocoding_count', 0)
        if skipped:
            alerts.append(
                warning(
                    'excluded_coordinates',
                    f'{skipped} same-state hospitals were excluded because coordinates were unavailable.',
                    'Ranking covers geocoded hospitals only; distances are straight-line miles, not travel time.',
                )
            )
        alignment = data.get('financial_alignment')
        if alignment is not None and alignment.get('fiscal_periods_match') is not True:
            alerts.append(
                warning(
                    'comparison_fiscal_alignment',
                    'The compared financial reports have different or unknown fiscal periods.',
                    'Treat reports as separate context; do not report direct financial differences.',
                )
            )
        if data.get('missing_fields'):
            alerts.append(
                warning(
                    'missing_financial_fields',
                    'Some financial source fields are missing.',
                    'Review the listed missing fields. Missing values do not mean zero.',
                    severity='info',
                    report_year=data.get('report_year'),
                )
            )
        for item in alerts:
            warning_fields = {}
            for copied_key, copied_value in (item).items():
                warning_fields[copied_key] = copied_value
            warning_fields['facility_id'] = facility_id
            warning_fields['facility_name'] = label

            item = warning_fields
            key = (facility_id, item['code'], item.get('metric'), item.get('report_year'))
            if key not in seen:
                seen.add(key)
                result.append(item)
        for field in ('indicators', 'financials', 'financial_trend', 'healthcare_access'):
            visit(data.get(field), facility_id, label)
        # Area county sections use a shared dictionary instead of hospital access rows.
        for county in data.get('counties', {}).values():
            visit(
                {
                    'county_demographics': county.get('demographics', {}),
                    'primary_care_hpsa': county.get('primary_care_hpsa', {}),
                },
                label=county.get('county'),
            )
        for report in data.get('hospital_reports', []):
            visit(report)

    visit(raw)
    return result
