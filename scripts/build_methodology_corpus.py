"""Download an allowlisted official methodology corpus; runtime retrieval stays offline."""
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime, timezone

import requests

ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = ROOT / 'data/reference/methodology/corpus.json'
SOURCES = [
    {'id': 'cms-cost-reports', 'title': 'CMS Cost Reports: General Information and Disclaimer',
     'url': 'https://www.cms.gov/data-research/statistics-trends-and-reports/cost-reports',
     'start': 'Disclaimer', 'end': 'New Cost Report Data Available', 'topic': 'cost reports financial data limitations'},
    {'id': 'hrsa-shortage', 'title': 'HRSA: What Is Shortage Designation?',
     'url': 'https://bhw.hrsa.gov/workforce-shortage-areas/shortage-designation',
     'start': 'What is a Health Professional Shortage Area', 'end': 'Date Last Reviewed', 'topic': 'hpsa shortage geographic population facility'},
    {'id': 'census-acs-testing', 'title': 'Census ACS: Statistical Testing Tool',
     'url': 'https://www.census.gov/programs-surveys/acs/guidance/statistical-testing-tool.html',
     'start': 'Comparing American Community Survey', 'end': 'Additional Resources', 'topic': 'acs population age estimates margin error statistical comparison'},
]


class TextExtractor(HTMLParser):
    """Extract body text without scripts, styles or hidden executable material."""
    def __init__(self):
        super().__init__()
        self.ignored = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.ignored += 1
        if tag in ('p', 'div', 'h1', 'h2', 'h3', 'li', 'br') and not self.ignored:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript') and self.ignored:
            self.ignored -= 1
        if tag in ('p', 'li') and not self.ignored:
            self.parts.append('\n')

    def handle_data(self, text):
        if not self.ignored:
            self.parts.append(text)


def build_corpus():
    """Refresh all sources atomically; fail instead of saving partial/empty evidence."""
    documents = []
    for source in SOURCES:
        response = requests.get(source['url'], timeout=45)
        # A reviewed official excerpt is explicit fallback evidence, not a fresh download.
        if response.status_code == 403 and source['id'] == 'hrsa-shortage':
            fallback = json.loads((CORPUS_PATH.parent / 'hrsa_reviewed_excerpt.json').read_text(encoding='utf-8'))
            content = fallback['content']
            digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
            if digest != fallback['content_sha256'] or fallback['source_url'] != source['url']:
                raise ValueError('Reviewed HRSA excerpt integrity check failed.')
            documents.append({
                'id': source['id'], 'title': source['title'], 'url': source['url'],
                'topic': source['topic'], 'publisher': urlparse(source['url']).hostname,
                'retrieved_at': fallback['reviewed_at'], 'publication_date': None,
                'content': content, 'content_sha256': digest,
                'extraction_method': 'reviewed_official_excerpt', 'source_kind': 'official',
            })
            print(source['id'], len(content), 'characters (reviewed excerpt; HTTP 403)')
            continue
        response.raise_for_status()
        if urlparse(response.url).hostname != urlparse(source['url']).hostname:
            raise ValueError('Unexpected redirect outside the approved source host.')
        extractor = TextExtractor()
        extractor.feed(response.text)
        lines = []
        for line in ''.join(extractor.parts).splitlines():
            normalized = ' '.join(line.split())
            if normalized:
                lines.append(normalized)
        text = '\n'.join(lines)
        start = text.find(source['start'])
        if start < 0:
            raise ValueError(f"Source layout changed: {source['id']} start marker missing.")
        text = text[start:]
        end = text.find(source['end'])
        if end < 0:
            raise ValueError(f"Source layout changed: {source['id']} end marker missing.")
        text = text[:end].strip()
        if len(text) < 250:
            raise ValueError('Source content too short for a methodology document.')
        documents.append({
            'id': source['id'], 'title': source['title'], 'url': response.url,
            'topic': source['topic'], 'publisher': urlparse(response.url).hostname,
            'retrieved_at': datetime.now(timezone.utc).isoformat(),
            'publication_date': None, 'content': text,
            'extraction_method': 'html_text_section', 'source_kind': 'official',
            'content_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
        })
        print(source['id'], len(text), 'characters')
    # Table excerpts retain the reviewed PDF page references and source checksum.
    supplement = json.loads((CORPUS_PATH.parent / 'cms_dictionary_passages.json').read_text(encoding='utf-8'))
    pdf_hash = hashlib.sha256((CORPUS_PATH.parent / 'cms_cost_report_dictionary.pdf').read_bytes()).hexdigest()
    if pdf_hash != supplement['source_pdf_sha256']:
        raise ValueError('CMS dictionary PDF changed; re-extract and review its table cells.')
    documents.extend(supplement['documents'])
    CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = CORPUS_PATH.with_suffix('.tmp')
    temporary.write_text(json.dumps({'schema_version': 1, 'documents': documents}, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(CORPUS_PATH)


if __name__ == '__main__':
    build_corpus()
