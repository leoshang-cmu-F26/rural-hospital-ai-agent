"""One-time, coordinate-aware extraction of the six-page CMS reference table."""

from collections import Counter
from hashlib import sha256
from pathlib import Path
import json
import re
import pdfplumber
import argparse

# Parse source and output paths.
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--pdf', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
# Read table rows using fixed column coordinates.
records = []
columns = [55, 333, 498, 626, 739, 787]
with pdfplumber.open(args.pdf) as pdf:
    for page_number, page in enumerate(pdf.pages, start=1):
        table = page.find_tables()[0]
        words = page.extract_words()
        for row in table.rows[1:]:
            values = []
            for index in range(5):
                cell_words = []
                for word in words:
                    center_y = (word['top'] + word['bottom']) / 2
                    if (
                        row.bbox[1] <= center_y < row.bbox[3]
                        and columns[index] <= word['x0'] < columns[index + 1]
                    ):
                        cell_words.append(word['text'])
                values.append(' '.join(cell_words))
            name, facility_type, ccn_text, city, state = values
            if 'Count' in name:
                continue
            ccns = re.findall(r'[0-9A-Z]+', ccn_text)
            assert all(values), (page_number, values)
            assert re.fullmatch('[A-Z]{2}', state), values
            for ccn in ccns:
                assert re.fullmatch(r'[0-9A-Z]{6,10}', ccn), values
            records.append(
                {
                    'record_id': f'cms-tribal-2020-{len(records)+1:03}',
                    'facility_name': name,
                    'facility_type': facility_type,
                    'ccns': ccns,
                    'city': city,
                    'state': state,
                    'source_page': page_number,
                }
            )
# Verify facility and CCN totals against the PDF subtotals.
counts = Counter()
ccn_counts = Counter()
for record in records:
    counts[record['facility_type']] += 1
    ccn_counts[record['facility_type']] += len(record['ccns'])
expected = {
    'Ambulatory Surgical Center': 1,
    'End Stage Renal Disease Facility': 5,
    'FQHC': 100,
    'Home Health Agency': 2,
    'Hospital': 42,
    'Nursing Facility': 1,
    'Rural Health Clinic': 7,
    'SNF/NF (Dually Certified)': 5,
}
record_counts_by_type = {}
for facility_type, count in counts.items():
    record_counts_by_type[facility_type] = count

ccn_counts_by_type = {}
for facility_type, count in ccn_counts.items():
    ccn_counts_by_type[facility_type] = count

assert record_counts_by_type == expected, (record_counts_by_type, expected)
# Preserve source provenance and write the reviewed JSON snapshot.
data = {
    'schema_version': 1,
    'source_title': 'IHS-CMS All Tribal Facilities Listing',
    'source_url': 'https://www.cms.gov/files/document/indian-healt-service-cms-all-final.pdf',
    'source_created_date': '2020-01-26',
    'source_sha256': sha256((args.pdf).read_bytes()).hexdigest(),
    'record_count': len(records),
    'ccn_count': sum(ccn_counts.values()),
    'record_counts_by_type': record_counts_by_type,
    'ccn_counts_by_type': ccn_counts_by_type,
    'records': records,
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
print('Extracted', len(records), 'facility rows and', sum(ccn_counts.values()), 'CCN entries.')
for record in records:
    if record['state'] == 'WI' or len(record['ccns']) > 1:
        print(record)
