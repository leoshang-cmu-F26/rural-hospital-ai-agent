"""Two-hospital comparison with explicit report-year and fiscal alignment."""

import requests

from app.services.agent_progress import report_progress
from app.services.cms_service import get_hospital_by_id
from app.services.cost_report_service import get_available_report_years
from app.services.investigation_service import _section


def compare_hospitals(
    first_id,
    second_id,
    financial_lookup,
    trend_lookup,
    access_lookup,
    year=None,
    start_year=None,
    end_year=None,
):
    """Compare two hospitals without mixing report periods or hiding data gaps."""

    # 1. Validate two distinct CCNs and the optional financial-trend period.
    ids = [first_id.strip(), second_id.strip()]

    if not ids[0] or not ids[1] or ids[0].upper() == ids[1].upper():
        return {'error': 'Provide two distinct hospital CCNs.'}

    if start_year is not None and end_year is not None:
        if start_year > end_year:
            return {'error': 'start_year must not exceed end_year.'}

    # 2. Resolve both identities before requesting financial or access data.
    # Keep the user's first/second order for the returned comparison and deltas.
    targets = []

    for ccn in ids:
        try:
            target = get_hospital_by_id(ccn)
        except requests.RequestException:
            return {
                'error': 'Hospital identification could not be retrieved.',
                'facility_id': ccn,
            }

        if target is None:
            return {
                'error': 'Hospital not found; clarify identity before comparison.',
                'facility_id': ccn,
            }

        targets.append(target.model_dump())

    if targets[0]['facility_id'] == targets[1]['facility_id']:
        return {'error': 'Both CCNs resolve to the same hospital.'}

    # 3. Use the requested dataset year, or search available years newest first.
    report_progress('Finding a common financial report year for both hospitals…')

    try:
        if year is not None:
            years = [year]
        else:
            years = sorted(get_available_report_years(), reverse=True)
    except (requests.RequestException, ValueError):
        years = []

    checked = []
    latest = [None, None]
    chosen = None
    selected_year = None

    # 4. Retrieve both reports for each year and record their availability.
    # Save each hospital's newest retrieved report as an unaligned fallback.
    for candidate in years:
        values = []

        for index, ccn in enumerate(ids):
            hospital_name = targets[index]['facility_name']
            report_progress(
                f'Checking report year {candidate} for {hospital_name}…'
            )

            data = _section(
                financial_lookup,
                facility_id=ccn,
                year=candidate,
            )

            if data.get('available') and data.get('report_year') != candidate:
                data = {
                    'available': False,
                    'error': 'Returned report year does not match the requested year.',
                }

            if data.get('available') and latest[index] is None:
                latest[index] = data

            values.append(data)

        hospital_checks = []
        both_reports_available = True

        for index, data in enumerate(values):
            hospital_check = {
                'facility_id': ids[index],
                'available': data['available'],
            }

            if data.get('error'):
                hospital_check['error'] = data['error']

            hospital_checks.append(hospital_check)

            if not data.get('available'):
                both_reports_available = False

        checked.append({
            'year': candidate,
            'hospitals': hospital_checks,
        })

        if both_reports_available:
            selected_year = candidate
            chosen = values
            break

    # 5. If no common year was retrieved, retain individual reports for context.
    # These separately dated reports must not be treated as aligned financials.
    if chosen is None:
        chosen = []

        for value in latest:
            if value:
                chosen.append(value)
            else:
                chosen.append({
                    'available': False,
                    'error': 'No financial report retrieved in the checked years.',
                })

    # 6. A common dataset year is not enough: check actual fiscal start/end dates.
    # None means dates are incomplete; False means both periods exist but differ.
    same_fiscal = None

    if selected_year is not None:
        periods = []
        all_dates_available = True

        for value in chosen:
            fiscal_year_begin = value.get('fiscal_year_begin')
            fiscal_year_end = value.get('fiscal_year_end')
            periods.append((fiscal_year_begin, fiscal_year_end))

            if not fiscal_year_begin or not fiscal_year_end:
                all_dates_available = False

        if all_dates_available:
            same_fiscal = periods[0] == periods[1]

    # 7. Preserve uncertainty when a newer year failed to load. A missing report
    # is different from an unresolved lookup and does not imply a service outage.
    newer_unavailable = []

    if selected_year is not None:
        for entry in checked:
            if entry['year'] <= selected_year:
                continue

            for item in entry['hospitals']:
                if 'error' in item and 'not found' not in item['error'].lower():
                    newer_unavailable.append(entry['year'])
                    break

    # 8. Describe the report-year selection and its fiscal comparability.
    if selected_year is None:
        alignment_note = (
            'No common report year was retrieved in the checked years. '
            'Separate reports are context only; no financial differences are calculated.'
        )
    elif year is not None:
        alignment_note = (
            'Requested financial dataset year; verify both fiscal periods.'
        )
    else:
        alignment_note = (
            'Latest successfully retrieved common dataset year; '
            'verify fiscal dates and unresolved newer years.'
        )

    alignment = {
        'common_report_year': selected_year,
        'requested_year': year,
        'same_dataset_year': selected_year is not None,
        'fiscal_periods_match': same_fiscal,
        'newer_years_with_unresolved_data': newer_unavailable,
        'years_checked': checked,
        'note': alignment_note,
    }

    # 9. Calculate second-minus-first deltas only for identical fiscal periods.
    # Skip missing values; percentage metrics use percentage points, not growth.
    differences = []

    if same_fiscal is True:
        metrics = (
            ('operating_margin', 'percentage_points'),
            ('occupancy_rate', 'percentage_points'),
            ('liability_to_asset_ratio', 'percentage_points'),
            ('cost_to_charge_ratio', 'ratio'),
        )

        for metric, unit in metrics:
            first = chosen[0].get('indicators', {}).get(metric)
            second = chosen[1].get('indicators', {}).get(metric)

            if first is not None and second is not None:
                differences.append({
                    'metric': metric,
                    'first': first,
                    'second': second,
                    'second_minus_first': round(second - first, 6),
                    'unit': unit,
                })

    # 10. Record alignment gaps before adding each hospital's evidence gaps.
    reports = []
    gaps = []

    if selected_year is None:
        gaps.append(
            'No retrieved common financial report year; financial results are not aligned.'
        )

    if same_fiscal is not True:
        gaps.append(
            'Fiscal periods differ or are unavailable; '
            'no direct financial differences are calculated.'
        )

    if newer_unavailable:
        gaps.append(
            'Some newer report years could not be resolved; do not claim '
            'the selected year is definitively the latest common year.'
        )

    # 11. Retrieve trends and healthcare-access evidence independently for each
    # hospital. Keep available sections even if another lookup is unavailable.
    for index, ccn in enumerate(ids):
        hospital_name = targets[index]['facility_name']
        report_progress(f'Reviewing financial trends for {hospital_name}…')
        trend = _section(
            trend_lookup,
            facility_id=ccn,
            start_year=start_year,
            end_year=end_year,
        )

        report_progress(f'Gathering healthcare-access evidence for {hospital_name}…')
        access = _section(access_lookup, facility_id=ccn)

        report = {
            'target_hospital': targets[index],
            'financials': chosen[index],
            'financial_trend': trend,
            'healthcare_access': access,
        }
        reports.append(report)

        # Record unavailable sections, missing indicators, and trend-year gaps.
        for key in ('financials', 'financial_trend', 'healthcare_access'):
            if not report[key]['available']:
                gaps.append(f'{ccn}: {key} unavailable')

        if chosen[index].get('indicators', {}).get('missing_fields'):
            gaps.append(f'{ccn}: some financial indicators are missing')

        if trend.get('years_without_report') or trend.get('years_unavailable'):
            gaps.append(f'{ccn}: financial trend has missing or unavailable years')

        # Access evidence may be available overall while individual county,
        # demographic, shortage, or distance sections still have coverage gaps.
        if access.get('available'):
            if access.get('county_comparison_available') is False:
                gaps.append(f'{ccn}: county hospital comparison unavailable')

            for key in ('county_demographics', 'primary_care_hpsa', 'distance_analysis'):
                if not access.get(key, {}).get('available'):
                    gaps.append(f'{ccn}: {key} unavailable')

            if access.get('distance_analysis', {}).get('skipped_geocoding_count'):
                gaps.append(
                    f'{ccn}: hospital distance ranking excludes unmatched coordinates'
                )

    # 12. Return the ordered evidence, calculated deltas, and explicit limits.
    # A partial status signals data gaps, not a hospital quality or risk rating.
    if gaps:
        status = 'partial'
    else:
        status = 'complete'

    return {
        'comparison_hospitals': targets,
        'hospital_reports': reports,
        'financial_alignment': alignment,
        'financial_differences': differences,
        'difference_direction': (
            'second hospital minus first hospital; not a quality or risk ranking'
        ),
        'data_gaps': gaps,
        'status': status,
        'limitations': [
            'Dataset years do not guarantee identical fiscal periods or accounting scope.',
            'Trends may cover different available years; compare actual years and missing data.',
            'County demographics and shortage designations describe county context, not hospital service areas.',
            'Distances use successfully geocoded same-state CMS candidates, not driving time or equivalent services.',
            'No overall winner, risk score or closure prediction is established.',
        ],
    }
