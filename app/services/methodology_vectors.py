"""OpenAI embeddings and private pgvector retrieval with explicit atomic ingestion."""

from copy import deepcopy
import hashlib
import json
import math
import os
from threading import Lock
import uuid

from cachetools import TTLCache
from openai import OpenAI, OpenAIError
from psycopg.types.json import Jsonb

from app.services import financial_store as store

DIMENSIONS = 1536
FORMAT_VERSION = 'title-topic-excerpt-chunk900-overlap100-v1'
_query_cache = TTLCache(maxsize=256, ttl=3600)
_cache_lock = Lock()


class MethodologyVectorUnavailable(Exception):
    """Public errors never disclose keys, request headers or connection strings."""


def embedding_model():
    """Use one configured model for both documents and queries."""
    model = os.getenv('METHODOLOGY_EMBEDDING_MODEL', 'text-embedding-3-small')
    if model not in ('text-embedding-3-small', 'text-embedding-3-large'):
        raise MethodologyVectorUnavailable('Unsupported methodology embedding model.')
    return model


def vector_literal(values):
    """Validate dimensionality, finiteness and nonzero length before PostgreSQL."""
    if not isinstance(values, list) or len(values) != DIMENSIONS:
        raise MethodologyVectorUnavailable('Invalid methodology embedding dimensions.')
    length = 0.0
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise MethodologyVectorUnavailable('Invalid methodology embedding values.')
        length += value * value
    if length == 0 or not math.isfinite(length):
        raise MethodologyVectorUnavailable('Invalid methodology embedding norm.')
    return json.dumps(values, allow_nan=False, separators=(',', ':'))


def embed_texts(texts, model):
    """Generate bounded batches and validate the response order explicitly."""
    if not os.getenv('OPENAI_API_KEY'):
        raise MethodologyVectorUnavailable('OPENAI_API_KEY is not configured for embeddings.')
    vectors = []
    try:
        with OpenAI(timeout=20, max_retries=1) as client:
            for offset in range(0, len(texts), 32):
                batch = texts[offset:offset + 32]
                response = client.embeddings.create(
                    model=model, dimensions=DIMENSIONS, input=batch, encoding_format='float')
                if response.model != model or len(response.data) != len(batch):
                    raise MethodologyVectorUnavailable('Embedding response model or count mismatch.')
                ordered = sorted(response.data, key=lambda item: item.index)
                for index, item in enumerate(ordered):
                    if item.index != index:
                        raise MethodologyVectorUnavailable('Embedding response order mismatch.')
                    vector_literal(item.embedding)
                    vectors.append(item.embedding)
    except OpenAIError:
        raise MethodologyVectorUnavailable('Methodology embedding service is unavailable.') from None
    return vectors


def load_passages():
    """Verify exact source spans and fingerprint the corpus plus embedding recipe."""
    from app.services import methodology_service as source

    payload = source.CORPUS_PATH.read_bytes()
    corpus_hash = hashlib.sha256(payload).hexdigest()
    corpus = json.loads(payload)
    if corpus.get('schema_version') != 1 or not corpus.get('documents'):
        raise MethodologyVectorUnavailable('Unsupported or empty methodology corpus.')
    model = embedding_model()
    fingerprint = hashlib.sha256(
        (corpus_hash + ':' + model + ':' + str(DIMENSIONS) + ':' + FORMAT_VERSION).encode()).hexdigest()
    passages = []
    seen = set()
    for document in corpus['documents']:
        content = document['content']
        if not content or hashlib.sha256(content.encode()).hexdigest() != document['content_sha256']:
            raise MethodologyVectorUnavailable('Methodology document checksum mismatch.')
        for index, (start, end, excerpt) in enumerate(source._chunks(content)):
            metadata = {}
            for key in ('title', 'url', 'publisher', 'retrieved_at', 'publication_date',
                        'source_kind', 'content_sha256', 'extraction_method', 'source_page'):
                metadata[key] = document.get(key)
            passage_id = document['id'] + ':' + str(index)
            if passage_id in seen:
                raise MethodologyVectorUnavailable('Duplicate methodology passage ID.')
            seen.add(passage_id)
            metadata['passage_id'] = passage_id
            metadata['start_offset'] = start
            metadata['end_offset'] = end
            text = document['title'] + '\n' + document['topic'] + '\n' + excerpt
            passages.append({'passage_id': passage_id, 'excerpt': excerpt, 'metadata': metadata,
                             'embedding_input': text,
                             'input_hash': hashlib.sha256(text.encode()).hexdigest()})
    return {'corpus_hash': corpus_hash, 'fingerprint': fingerprint,
            'model': model, 'passages': passages}


def initialize_schema():
    """Explicit migration only; runtime retrieval never creates tables or vectors."""
    path = store.ROOT / 'supabase/migrations/202610280001_methodology_vectors.sql'
    with store.connect() as connection:
        connection.execute(path.read_text(encoding='utf-8'))


def active_snapshot(fingerprint):
    """Reject stale corpora or mismatched embedding models before API calls."""
    rows = store._read('''SELECT c.id::text, c.passage_count
        FROM hospital_data.methodology_active a
        JOIN hospital_data.methodology_corpora c ON c.id=a.corpus_id
        WHERE a.name='methodology' AND c.fingerprint=%s''', (fingerprint,))
    if rows:
        return rows[0]
    return None


def import_vectors(init_db=False):
    """Reuse embeddings and publish a complete version atomically after validation."""
    prepared = load_passages()
    if init_db:
        initialize_schema()
    existing = active_snapshot(prepared['fingerprint'])
    if existing:
        return {'status': 'unchanged', 'passage_count': existing[1], 'embedding_requests_needed': 0}

    # Cache by embedding input/model; changed metadata does not require re-embedding.
    cached_rows = store._read('''SELECT p.embedding_input_sha256, p.embedding::text
        FROM hospital_data.methodology_passages p
        JOIN hospital_data.methodology_corpora c ON c.id=p.corpus_id
        WHERE c.embedding_model=%s AND c.embedding_dimensions=%s''',
        (prepared['model'], DIMENSIONS))
    cached = {}
    for digest, literal in cached_rows:
        values = json.loads(literal)
        vector_literal(values)
        cached[digest] = values
    missing_texts = []
    missing_hashes = []
    for passage in prepared['passages']:
        digest = passage['input_hash']
        if digest not in cached and digest not in missing_hashes:
            missing_hashes.append(digest)
            missing_texts.append(passage['embedding_input'])
    if missing_texts:
        generated = embed_texts(missing_texts, prepared['model'])
        for digest, vector in zip(missing_hashes, generated):
            cached[digest] = vector

    # Rows, audit metadata and active pointer commit together; failures retain old data.
    corpus_id = uuid.uuid4()
    with store.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '30s'")
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext('methodology-vectors'))")
            cursor.execute('''INSERT INTO hospital_data.methodology_corpora
                (id, fingerprint, corpus_sha256, embedding_model, embedding_dimensions, passage_count)
                VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(fingerprint) DO NOTHING RETURNING id''',
                (corpus_id, prepared['fingerprint'], prepared['corpus_hash'],
                 prepared['model'], DIMENSIONS, len(prepared['passages'])))
            inserted = cursor.fetchone()
            if inserted:
                for passage in prepared['passages']:
                    cursor.execute('''INSERT INTO hospital_data.methodology_passages
                        (corpus_id, passage_id, excerpt, source_metadata, embedding_input_sha256, embedding)
                        VALUES (%s,%s,%s,%s,%s,%s::extensions.vector)''',
                        (corpus_id, passage['passage_id'], passage['excerpt'], Jsonb(passage['metadata']),
                         passage['input_hash'], vector_literal(cached[passage['input_hash']])))
            else:
                cursor.execute('SELECT id FROM hospital_data.methodology_corpora WHERE fingerprint=%s',
                               (prepared['fingerprint'],))
                corpus_id = cursor.fetchone()[0]
            cursor.execute('SELECT count(*) FROM hospital_data.methodology_passages WHERE corpus_id=%s',
                           (corpus_id,))
            if cursor.fetchone()[0] != len(prepared['passages']):
                raise MethodologyVectorUnavailable('Methodology passage count mismatch.')
            cursor.execute('''INSERT INTO hospital_data.methodology_active(name,corpus_id)
                VALUES ('methodology',%s) ON CONFLICT(name) DO UPDATE SET corpus_id=EXCLUDED.corpus_id''',
                (corpus_id,))
    return {'status': 'complete', 'passage_count': len(prepared['passages']),
            'newly_embedded_passages': len(missing_texts), 'model': prepared['model'],
            'dimensions': DIMENSIONS}


def retrieve_vectors(query, limit=3):
    """Query exact cosine neighbors over the active corpus, with a minimum score."""
    prepared = load_passages()
    snapshot = active_snapshot(prepared['fingerprint'])
    if snapshot is None:
        raise MethodologyVectorUnavailable('Methodology vectors are missing or stale; run the vector import job.')
    threshold = float(os.getenv('METHODOLOGY_MIN_SIMILARITY', '0.30'))
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise MethodologyVectorUnavailable('Invalid methodology similarity threshold.')
    key = (prepared['model'], query)
    with _cache_lock:
        vector = _query_cache.get(key)
    if vector is None:
        vector = embed_texts([query], prepared['model'])[0]
        with _cache_lock:
            _query_cache[key] = vector
    literal = vector_literal(vector)
    rows = store._read('''SELECT excerpt, source_metadata,
        1 - (embedding OPERATOR(extensions.<=>) %s::extensions.vector) AS similarity
        FROM hospital_data.methodology_passages WHERE corpus_id=%s
        ORDER BY embedding OPERATOR(extensions.<=>) %s::extensions.vector, passage_id
        LIMIT %s''', (literal, snapshot[0], literal, limit))
    passages = []
    expected_passages = {}
    for passage in prepared['passages']:
        expected_passages[passage['passage_id']] = passage
    for excerpt, metadata, similarity in rows:
        if similarity is None or not math.isfinite(similarity) or similarity < threshold:
            continue
        expected = expected_passages.get(metadata.get('passage_id'))
        if expected is None or excerpt != expected['excerpt'] or metadata != expected['metadata']:
            raise MethodologyVectorUnavailable('Stored methodology passage provenance mismatch.')
        passage = deepcopy(metadata)
        passage['excerpt'] = excerpt
        passage['similarity'] = float(similarity)
        passages.append(passage)
    return {'report_kind': 'methodology_retrieval', 'available': True,
            'retrieval_method': 'OpenAI embeddings / PostgreSQL pgvector cosine similarity',
            'embedding_model': prepared['model'], 'embedding_dimensions': DIMENSIONS,
            'corpus_fingerprint': prepared['fingerprint'], 'min_similarity': threshold,
            'has_matches': bool(passages), 'passages': passages,
            'limitations': ['Similarity is not factual confidence or proof that a passage supports the claim.',
                           'Versioned source snapshots; retrieval dates are not publication dates.',
                           'Use structured tools for hospital identities and numeric observations.']}
