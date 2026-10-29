"""Offline vector RAG contracts; no real database or embedding API calls."""

from unittest.mock import Mock

import pytest

from app.services import methodology_service as service
from app.services import methodology_vectors as vectors
from app.services import financial_store as store


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv('METHODOLOGY_RETRIEVAL_MODE', 'vector')
    monkeypatch.setenv('METHODOLOGY_EMBEDDING_MODEL', 'text-embedding-3-small')
    monkeypatch.setenv('METHODOLOGY_MIN_SIMILARITY', '0.30')
    vectors._query_cache.clear()
    prepared = vectors.load_passages()
    passage = prepared['passages'][0]
    vector = [0.0] * vectors.DIMENSIONS
    vector[0] = 1.0
    embed = Mock(return_value=[vector])
    monkeypatch.setattr(vectors, 'embed_texts', embed)
    def read(sql, parameters=()):
        if 'methodology_active' in sql:
            return [('test-corpus', len(prepared['passages']))]
        return [(passage['excerpt'], passage['metadata'], 0.8)]
    monkeypatch.setattr(store, '_read', Mock(side_effect=read))
    return prepared, embed


def test_vector_is_default_and_retains_exact_provenance(configured, monkeypatch):
    monkeypatch.delenv('METHODOLOGY_RETRIEVAL_MODE')
    result = service.retrieve_methodology('What is a cost report?')
    assert result['available'] and result['has_matches']
    assert 'pgvector' in result['retrieval_method']
    assert result['embedding_dimensions'] == 1536
    assert result['passages'][0]['similarity'] == 0.8
    expected = configured[0]['passages'][0]
    assert result['passages'][0]['excerpt'] == expected['excerpt']
    assert result['passages'][0]['content_sha256'] == expected['metadata']['content_sha256']


def test_repeated_query_reuses_embedding_but_reads_current_snapshot(configured):
    service.retrieve_methodology('question')
    service.retrieve_methodology('question', limit=1)
    configured[1].assert_called_once()
    assert store._read.call_count == 4


def test_low_similarity_is_empty_not_service_failure(configured, monkeypatch):
    monkeypatch.setenv('METHODOLOGY_MIN_SIMILARITY', '0.9')
    result = service.retrieve_methodology('unrelated question')
    assert result['available'] and not result['has_matches']
    assert result['passages'] == []


def test_stale_index_does_not_embed_or_fallback(configured, monkeypatch):
    monkeypatch.setattr(vectors, 'active_snapshot', lambda fingerprint: None)
    lexical = Mock(side_effect=AssertionError('No silent fallback'))
    monkeypatch.setattr(service, 'retrieve_lexical_methodology', lexical)
    result = service.retrieve_methodology('question')
    assert result['available'] is False
    assert 'stale' in result['error']
    configured[1].assert_not_called()


def test_database_failure_and_embedding_failure_are_unavailable(configured, monkeypatch):
    monkeypatch.setattr(store, '_read', Mock(side_effect=store.FinancialStoreUnavailable('private details')))
    result = service.retrieve_methodology('question')
    assert result['available'] is False
    assert 'private details' not in result['error']
    monkeypatch.setattr(vectors, 'active_snapshot', lambda fingerprint: ('id', 16))
    monkeypatch.setattr(vectors, 'embed_texts', Mock(side_effect=vectors.MethodologyVectorUnavailable('Embedding service unavailable.')))
    assert service.retrieve_methodology('question')['available'] is False


def test_modified_stored_excerpt_fails_closed(configured, monkeypatch):
    metadata = configured[0]['passages'][0]['metadata']
    monkeypatch.setattr(vectors, 'active_snapshot', lambda fingerprint: ('id', 16))
    monkeypatch.setattr(store, '_read', lambda *args: [('altered text', metadata, 0.8)])
    assert service.retrieve_methodology('question')['available'] is False


def test_unchanged_import_does_not_generate_embeddings(configured):
    result = vectors.import_vectors()
    assert result['status'] == 'unchanged'
    configured[1].assert_not_called()


def test_fingerprint_changes_with_embedding_model(configured, monkeypatch):
    first = vectors.load_passages()['fingerprint']
    monkeypatch.setenv('METHODOLOGY_EMBEDDING_MODEL', 'text-embedding-3-large')
    assert vectors.load_passages()['fingerprint'] != first


@pytest.mark.parametrize('value', [[], [0.0] * 1536, [float('nan')] * 1536,
                                  [float('inf')] * 1536, [True] * 1536])
def test_invalid_vectors_rejected(value):
    with pytest.raises(vectors.MethodologyVectorUnavailable):
        vectors.vector_literal(value)


@pytest.mark.parametrize('query,limit', [('', 3), ('x' * 601, 3), ('test', 0), ('test', True)])
def test_input_bounds_precede_embedding_calls(configured, query, limit):
    assert 'error' in service.retrieve_methodology(query, limit)
    configured[1].assert_not_called()


def test_embedding_sdk_parameters_and_order(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'offline-test-value')
    vector = [1.0] + [0.0] * 1535
    response = Mock(model='text-embedding-3-small', data=[Mock(index=0, embedding=vector)])
    client = Mock()
    client.embeddings.create.return_value = response
    context = Mock()
    context.__enter__ = Mock(return_value=client)
    context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(vectors, 'OpenAI', Mock(return_value=context))
    assert vectors.embed_texts(['public passage'], 'text-embedding-3-small') == [vector]
    client.embeddings.create.assert_called_once_with(
        model='text-embedding-3-small', dimensions=1536, input=['public passage'], encoding_format='float')
