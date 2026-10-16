"""Small factual metadata for the UI; exclude full records and model reasoning."""
import json


def evidence_summary(output):
    raw = getattr(output, 'content', output)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    if not isinstance(raw, dict):
        return []
    if 'hospital_reports' in raw and 'financial_alignment' in raw:
        combined = []
        for report in raw['hospital_reports'][:2]:
            target = report.get('target_hospital', {})
            for row in evidence_summary(report):
                if row['key'] == 'financials':
                    row['label'] = ('Common-year financial report' if raw['financial_alignment'].get('same_dataset_year')
                                    else 'Unaligned financial report')
                row['key'] = str(target.get('facility_id', 'unknown')) + ':' + row['key']
                row['label'] = str(target.get('facility_name', 'Hospital')) + ' — ' + row['label']
                combined.append(row)
        alignment = raw['financial_alignment']
        good = alignment.get('same_dataset_year') and alignment.get('fiscal_periods_match') is True
        combined.insert(0, {
            'key': 'comparison_alignment', 'label': 'Financial report alignment',
            'status': 'available' if good and not alignment.get('newer_years_with_unresolved_data') else 'partial',
            'source': 'CMS Hospital Provider Cost Report',
            'period': str(alignment.get('common_report_year') or 'No common year retrieved'),
            'details': alignment['note'] + (' Fiscal dates differ or are unavailable; no direct differences calculated.' if not good else ''),
        })
        return combined
    rows = []

    def add(key, label, data, source=None):
        if not isinstance(data, dict):
            return
        available = data.get('available', 'error' not in data)
        gaps = []
        missing = data.get('missing_fields') or data.get('indicators', {}).get('missing_fields')
        if missing:
            gaps.append('Missing fields: ' + ', '.join(str(x) for x in missing))
        if data.get('years_without_report'):
            gaps.append('No matching report: ' + ', '.join(map(str, data['years_without_report'])))
        if data.get('years_unavailable'):
            gaps.append('Unavailable years: ' + ', '.join(map(str, data['years_unavailable'])))
        skipped = data.get('skipped_geocoding_count', 0)
        if skipped:
            gaps.append(f'{skipped} hospitals excluded from coordinate ranking')
        if key == 'distance_analysis':
            gaps.append('Same-state candidates; straight-line miles; capacity and eligibility not assessed')
            if available and not data.get('nearest_hospitals'):
                gaps.append('No hospitals could be ranked from available coordinates')
        row = {'key': key, 'label': label,
               'status': 'unavailable' if not available else ('partial' if gaps and key != 'distance_analysis' else 'available'),
               'source': str(data.get('source') or source or 'See analysis')[:200]}
        if available and skipped:
            row['status'] = 'partial'
        if data.get('report_year') is not None:
            row['period'] = str(data['report_year'])
        elif data.get('years_with_data'):
            row['period'] = ', '.join(map(str, data['years_with_data']))
        if data.get('fiscal_year_begin') and data.get('fiscal_year_end'):
            row['fiscal_period'] = f"{data['fiscal_year_begin']} – {data['fiscal_year_end']}"
        if data.get('error'):
            gaps.append(str(data['error'])[:250])
        if gaps:
            row['details'] = '; '.join(gaps)[:700]
        rows.append(row)

    if 'financials' in raw:
        add('financials', 'Latest financial report', raw['financials'], 'CMS Hospital Provider Cost Report')
        add('financial_trend', 'Financial trend', raw.get('financial_trend'), 'CMS Hospital Provider Cost Report')
        access = raw.get('healthcare_access', {})
        if not access.get('available'):
            add('healthcare_access', 'Healthcare access', access, 'CMS / Census / HRSA')
        else:
            raw = access
    if 'indicators' in raw:
        add('financials', 'Financial report', raw)
    if 'yearly_indicators' in raw:
        add('financial_trend', 'Financial trend', raw)
    if 'alternative_hospital_count' in raw:
        add('county_comparison', 'Same-county hospital comparison', {
            'available': raw.get('county_comparison_available', True),
            **({'error': raw['county_comparison_error']} if raw.get('county_comparison_error') else {}),
        }, 'CMS Hospital General Information')
    for key, label, source in (
        ('county_demographics', 'County demographics', 'U.S. Census Bureau ACS'),
        ('primary_care_hpsa', 'Primary-care shortage evidence', 'HRSA'),
        ('distance_analysis', 'Nearest same-state hospitals', 'CMS; Census Geocoder; Haversine'),
        ('location', 'Address match', 'U.S. Census Bureau Geocoder'),
    ):
        add(key, label, raw.get(key), source)
    return rows
