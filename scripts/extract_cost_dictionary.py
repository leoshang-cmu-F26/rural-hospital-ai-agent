"""Developer-only PDF table extraction; requires pdfplumber, not a runtime dependency."""

import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / 'data/reference/methodology'
PDF = DIRECTORY / 'cms_cost_report_dictionary.pdf'
SOURCE_URL = 'https://data.cms.gov/sites/default/files/2024-03/9756088d-5280-4090-80b9-449d31ef25a3/Cost%20Report%20Data%20Dictionary%20Update.pdf'
FIELDS = (
    'Rural versus Urban',
    'Fiscal Year Begin Date',
    'Fiscal Year End Date',
    'Total Bed Days Available',
    'Total Assets',
    'Total Liabilities',
    'Net Patient Revenue',
    'Net Income from Service to Patients',
    'Net Income',
    'Cost To Charge Ratio',
)


def extract():
    """Keep complete table cells, worksheet references and one-based PDF page citations."""
    documents = []
    matched = set()
    expected = set()
    for name in FIELDS:
        expected.add(name.casefold())
    with pdfplumber.open(PDF) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row in table:
                    if len(row) < 3:
                        continue
                    field = ' '.join((row[0] or '').split())
                    if field.casefold() not in expected:
                        continue
                    worksheet = ' '.join((row[1] or '').split())
                    definition = ' '.join((row[2] or '').split())
                    if not definition:
                        raise ValueError('Missing definition for ' + field)
                    text = f'Field: {field}\nWorksheet: {worksheet}\nDefinition: {definition}'
                    documents.append(
                        {
                            'id': 'cms-dictionary-' + str(len(documents)),
                            'title': 'CMS Hospital Provider Cost Report Data Dictionary: ' + field,
                            'url': SOURCE_URL + '#page=' + str(page_number),
                            'topic': field,
                            'publisher': 'data.cms.gov',
                            'source_kind': 'official',
                            'retrieved_at': datetime.now(timezone.utc).isoformat(),
                            'publication_date': None,
                            'content': text,
                            'content_sha256': hashlib.sha256(text.encode()).hexdigest(),
                            'source_page': page_number,
                            'extraction_method': 'pdf_table_cells',
                        }
                    )
                    matched.add(field.casefold())
    for name in FIELDS:
        if name.casefold() not in matched:
            raise ValueError('Expected dictionary field missing: ' + name)
    result = {
        'source_pdf_sha256': hashlib.sha256(PDF.read_bytes()).hexdigest(),
        'documents': documents,
    }
    (DIRECTORY / 'cms_dictionary_passages.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print('Extracted', len(documents), 'definitions with page citations.')


if __name__ == '__main__':
    extract()
