"""Methodology RAG: pgvector by default, with explicit legacy lexical retrieval."""

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from threading import Lock

ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = ROOT / 'data/reference/methodology/corpus.json'
INDEX_PATH = ROOT / 'data/methodology.db'
_INDEX_LOCK = Lock()
STOPWORDS = {
    'the',
    'a',
    'an',
    'is',
    'are',
    'was',
    'what',
    'why',
    'does',
    'do',
    'how',
    'can',
    'of',
    'for',
    'to',
    'and',
    'or',
    'in',
    'this',
    'that',
    'with',
    'mean',
    'explain',
    'please',
    'it',
    'my',
}
ALIASES = {
    'hpsa': ['shortage', 'population', 'facility'],
    'operating margin': ['net', 'income', 'service', 'patients'],
    'liability': ['liabilities', 'assets'],
    'occupancy': ['bed', 'days', 'available'],
    'acs': ['estimates', 'margin', 'error'],
    '财务': ['cost', 'report', 'financial'],
    '财年': ['fiscal', 'period'],
    '人口': ['population', 'estimates'],
    '统计': ['statistical', 'testing'],
    '误差': ['margin', 'error'],
    '短缺': ['shortage', 'hpsa'],
    '利润率': ['operating', 'margin'],
    '负资产': ['negative', 'assets'],
}


# Exact document passages


def _chunks(text, size=900):
    """Keep exact text spans and offsets, with small overlap across boundaries."""
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        yield start, end, text[start:end]
        if end == len(text):
            break
        start = end - 100


# Verified local search index


def initialize_methodology_index():
    """Atomically rebuild the FTS5 index only when the versioned corpus changes."""
    payload = CORPUS_PATH.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    corpus = json.loads(payload)
    if corpus.get('schema_version') != 1 or not corpus.get('documents'):
        raise ValueError('Unsupported or empty methodology corpus.')
    # Verify every stored source before trusting either an existing or a new index.
    for document in corpus['documents']:
        actual = hashlib.sha256(document['content'].encode('utf-8')).hexdigest()
        if actual != document['content_sha256']:
            raise ValueError('Methodology document checksum mismatch.')
    with _INDEX_LOCK:
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(INDEX_PATH, timeout=10)) as connection:
            with connection:
                connection.execute(
                    'CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)'
                )
                connection.execute(
                    'CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(title, topic, content, source_json UNINDEXED)'
                )
                cached = connection.execute(
                    "SELECT value FROM metadata WHERE key='corpus_sha256'"
                ).fetchone()
                if cached and cached[0] == digest:
                    return
                connection.execute('DELETE FROM passages')
                for document in corpus['documents']:
                    for index, (start, end, content) in enumerate(_chunks(document['content'])):
                        metadata = {}
                        for key in (
                            'title',
                            'url',
                            'publisher',
                            'retrieved_at',
                            'publication_date',
                            'source_kind',
                            'content_sha256',
                            'extraction_method',
                            'source_page',
                        ):
                            metadata[key] = document.get(key)
                        metadata['passage_id'] = document['id'] + ':' + str(index)
                        metadata['start_offset'] = start
                        metadata['end_offset'] = end
                        connection.execute(
                            'INSERT INTO passages(title, topic, content, source_json) VALUES (?, ?, ?, ?)',
                            (document['title'], document['topic'], content, json.dumps(metadata)),
                        )
                connection.execute(
                    "INSERT OR REPLACE INTO metadata VALUES ('corpus_sha256', ?)", (digest,)
                )


# Bounded passage retrieval


def retrieve_lexical_methodology(query, limit=3):
    """Return evidence passages, never a fabricated answer or live hospital facts."""
    # 1. Bound input and expand a small reviewed vocabulary, including Chinese terms.
    if not isinstance(query, str) or not query.strip() or len(query) > 600:
        return {'error': 'Provide a methodology question of 1–600 characters.'}
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 4:
        return {'error': 'limit must be between 1 and 4.'}
    tokens = []
    for token in re.findall(r'[a-z0-9]+', query.lower()):
        if len(token) > 1 and token not in STOPWORDS and token not in tokens:
            tokens.append(token)
    for key, expansion in ALIASES.items():
        if key in query.lower():
            for token in expansion:
                if token not in tokens:
                    tokens.append(token)
    result = {
        'report_kind': 'methodology_retrieval',
        'retrieval_method': 'SQLite FTS5 / BM25 lexical retrieval',
        'available': True,
        'passages': [],
        'has_matches': False,
        'limitations': [
            'Versioned document snapshots; retrieval dates are not publication dates or proof of current policy.',
            'Passages explain methods only. Use structured tools for hospital identities, classifications and numbers.',
            'Lexical matches are not semantic confidence. If passages do not support the question, say evidence is insufficient.',
        ],
    }
    if not tokens:
        return result
    # 2. Build/reuse the local index. Query text never becomes raw FTS or SQL syntax.
    try:
        initialize_methodology_index()
        query_parts = []
        for token in tokens[:35]:
            query_parts.append('"' + token + '"')
        expression = ' OR '.join(query_parts)
        with closing(sqlite3.connect(INDEX_PATH, timeout=10)) as connection:
            rows = connection.execute(
                'SELECT content, source_json FROM passages WHERE passages MATCH ? ORDER BY bm25(passages, 2, 0.2, 1, 0) LIMIT ?',
                (expression, limit),
            ).fetchall()
        # 3. Return only capped passages with exact provenance for cited generation.
        for content, metadata in rows:
            passage_data = {}
            for copied_key, copied_value in (json.loads(metadata)).items():
                passage_data[copied_key] = copied_value
            passage_data['excerpt'] = content

            result['passages'].append(passage_data)
        result['has_matches'] = bool(rows)
        # A match is only retrieval support; the model must still check entailment.
        result['support_note'] = (
            'has_matches means matching passages exist, not that every claim in the question is established.'
        )
        return result
    except (OSError, ValueError, sqlite3.Error):
        error_response = {}
        for copied_key, copied_value in (result).items():
            error_response[copied_key] = copied_value
        error_response['available'] = False
        error_response['error'] = 'Methodology corpus or local search index unavailable.'

        return error_response


# Vector retrieval is the default; lexical retrieval requires an explicit setting.


def retrieve_methodology(query, limit=3):
    """Keep the Agent tool stable while switching its retrieval backend."""
    if not isinstance(query, str) or not query.strip() or len(query) > 600:
        return {'error': 'Provide a methodology question of 1–600 characters.'}
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 4:
        return {'error': 'limit must be between 1 and 4.'}
    mode = os.getenv('METHODOLOGY_RETRIEVAL_MODE', 'vector')
    if mode == 'lexical':
        return retrieve_lexical_methodology(query, limit)
    if mode != 'vector':
        return {'available': False, 'has_matches': False, 'passages': [],
                'error': 'Invalid METHODOLOGY_RETRIEVAL_MODE.'}
    from app.services import methodology_vectors as vectors
    from app.services.financial_store import FinancialStoreUnavailable

    try:
        return vectors.retrieve_vectors(query.strip(), limit)
    except vectors.MethodologyVectorUnavailable as error:
        message = str(error)
    except (OSError, ValueError, KeyError, TypeError, FinancialStoreUnavailable):
        message = 'Methodology vector corpus or database unavailable.'
    return {'report_kind': 'methodology_retrieval', 'available': False,
            'retrieval_method': 'OpenAI embeddings / PostgreSQL pgvector cosine similarity',
            'has_matches': False, 'passages': [], 'error': message}
