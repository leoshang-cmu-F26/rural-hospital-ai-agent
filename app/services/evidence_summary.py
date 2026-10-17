"""Small factual metadata for the UI; exclude full records and model reasoning."""
import json


def evidence_summary(output):
    """Build compact source, period and availability cards from real tool results."""
    # 1. Decode structured tool output; ignore prose and unsupported payloads.
    raw = getattr(output, 'content', output)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    if not isinstance(raw, dict):
        return []
    # Historical references have a source date, not verified current coverage.
    if raw.get('directory_kind') == 'historical_tribal_facilities':
        return [{
            'key': 'tribal_directory', 'label': 'Historical tribal facility directory',
            'status': 'partial', 'source': raw['source'],
            'period': raw['source_created_date'],
            'details': 'Historical source only; current operation, certification and affiliation are unverified. See cited PDF pages in the answer.',
        }]
    # 2. Prefix comparison cards by CCN so the two hospitals cannot overwrite each other.
    if 'hospital_reports' in raw and 'financial_alignment' in raw:
        combined = []
        for report in raw['hospital_reports'][:2]:
            target = report.get('target_hospital', {})
            for row in evidence_summary(report):
                if row['key'] == 'financials':
                    if raw['financial_alignment'].get('same_dataset_year'):
                        row['label'] = 'Common-year financial report'
                    else:
                        row['label'] = 'Unaligned financial report'
                row['key'] = str(target.get('facility_id', 'unknown')) + ':' + row['key']
                row['label'] = str(target.get('facility_name', 'Hospital')) + ' — ' + row['label']
                combined.append(row)
        alignment = raw['financial_alignment']
        good = alignment.get('same_dataset_year') and alignment.get('fiscal_periods_match') is True
        if good and not alignment.get('newer_years_with_unresolved_data'):
            alignment_status = 'available'
        else:
            alignment_status = 'partial'
        alignment_details = alignment['note']
        if not good:
            alignment_details += ' Fiscal dates differ or are unavailable; no direct differences calculated.'
        combined.insert(0, {
            'key': 'comparison_alignment', 'label': 'Financial report alignment',
            'status': alignment_status,
            'source': 'CMS Hospital Provider Cost Report',
            'period': str(alignment.get('common_report_year') or 'No common year retrieved'),
            'details': alignment_details,
        })
        return combined
    rows = []

    # 3. Build one compact card with availability, source, periods and explicit gaps.
    def add(key, label, data, source=None):
        if not isinstance(data, dict):
            return
        available = data.get('available', 'error' not in data)
        gaps = []
        missing = data.get('missing_fields') or data.get('indicators', {}).get('missing_fields')
        if missing:
            field_names = []
            for field_name in missing:
                field_names.append(str(field_name))
            gaps.append('Missing fields: ' + ', '.join(field_names))
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
        # Missing data is distinct from a negative clinical or financial finding.
        if not available:
            status = 'unavailable'
        elif gaps and key != 'distance_analysis':
            status = 'partial'
        else:
            status = 'available'
        row = {'key': key, 'label': label,
               'status': status,
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

    # 4. Unwrap full investigations; standalone financial tools remain supported.
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
    # 5. Keep an unavailable county distinct from a zero-hospital county.
    if 'alternative_hospital_count' in raw:
        county_comparison = {
            'available': raw.get('county_comparison_available', True),
        }
        if raw.get('county_comparison_error'):
            county_comparison['error'] = raw['county_comparison_error']
        add('county_comparison', 'Same-county hospital comparison',
            county_comparison, 'CMS Hospital General Information')
    # 6. Retain independent county, shortage, distance and address evidence cards.
    for key, label, source in (
        ('county_demographics', 'County demographics', 'U.S. Census Bureau ACS'),
        ('primary_care_hpsa', 'Primary-care shortage evidence', 'HRSA'),
        ('distance_analysis', 'Nearest same-state hospitals', 'CMS; Census Geocoder; Haversine'),
        ('location', 'Address match', 'U.S. Census Bureau Geocoder'),
    ):
        add(key, label, raw.get(key), source)
    return rows
