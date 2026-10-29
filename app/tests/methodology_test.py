"""RAG retrieval tests: provenance, index persistence, bounds and unsupported queries."""
import hashlib
import json
from unittest.mock import patch

import pytest

from app.services import methodology_service as service
from app.services.chat_context import extract_facility


@pytest.fixture(autouse=True)
def local_index(tmp_path, monkeypatch):
    monkeypatch.setenv('METHODOLOGY_RETRIEVAL_MODE', 'lexical')
    monkeypatch.setattr(service, 'INDEX_PATH', tmp_path / 'methodology.db')


def test_hrsa_question_retrieves_original_official_passage():
    result = service.retrieve_methodology('What is a population HPSA?')
    assert result['available'] and result['has_matches']
    passage = result['passages'][0]
    assert 'bhw.hrsa.gov' in passage['url']
    assert 'specific group of people' in passage['excerpt']
    assert passage['retrieved_at']
    assert passage['publication_date'] is None


def test_census_uncertainty_and_chinese_query_expansion():
    for question in ('Explain ACS margin of error', '人口统计误差有什么影响？'):
        result = service.retrieve_methodology(question)
        assert 'census.gov' in result['passages'][0]['url']


def test_dictionary_definition_has_verified_pdf_page():
    result = service.retrieve_methodology('Net patient revenue definition')
    passage = result['passages'][0]
    assert passage['source_page'] == 9
    assert passage['url'].endswith('#page=9')
    assert 'Definition:' in passage['excerpt']


def test_passages_are_exact_source_spans_with_hashes():
    corpus = json.loads(service.CORPUS_PATH.read_text(encoding='utf-8'))
    docs = {}
    for document in corpus['documents']:
        docs[document['content_sha256']] = document
    for passage in service.retrieve_methodology('cost report financial', limit=4)['passages']:
        doc = docs[passage['content_sha256']]
        assert doc['content'][passage['start_offset']:passage['end_offset']] == passage['excerpt']
        assert len(passage['excerpt']) <= 900


def test_unrelated_question_has_no_fabricated_answer():
    result = service.retrieve_methodology('zzunrelatedgibberish')
    assert result['passages'] == []
    assert result['has_matches'] is False
    assert 'answer' not in result


def test_invalid_inputs_and_fts_operators_are_safe():
    for question in ('', 'a' * 601):
        assert 'error' in service.retrieve_methodology(question)
    for limit in (0, 5, True):
        assert 'error' in service.retrieve_methodology('HPSA', limit)
    result = service.retrieve_methodology('HPSA ") OR * NEAR / -- DROP TABLE passages')
    assert result['available']
    assert service.retrieve_methodology('HPSA')['passages']


def test_existing_index_is_reused_without_network():
    first = service.retrieve_methodology('HPSA')
    with patch('requests.get', side_effect=AssertionError('Runtime must be offline')):
        second = service.retrieve_methodology('HPSA')
    assert first['passages'] == second['passages']


def test_missing_or_tampered_corpus_is_unavailable_not_no_match(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'CORPUS_PATH', tmp_path / 'missing.json')
    assert service.retrieve_methodology('HPSA')['available'] is False
    service.CORPUS_PATH.write_text(json.dumps({'schema_version': 1, 'documents': [
        {'content': 'tampered', 'content_sha256': 'wrong'}]}), encoding='utf-8')
    result = service.retrieve_methodology('HPSA')
    assert result['available'] is False
    assert result['has_matches'] is False


def test_corpus_change_rebuilds_existing_index(tmp_path, monkeypatch):
    path = tmp_path / 'corpus.json'
    path.write_bytes(service.CORPUS_PATH.read_bytes())
    monkeypatch.setattr(service, 'CORPUS_PATH', path)
    service.retrieve_methodology('HPSA')
    corpus = json.loads(path.read_text(encoding='utf-8'))
    corpus['documents'][0]['content'] += '\nzznewuniquetoken'
    corpus['documents'][0]['content_sha256'] = hashlib.sha256(corpus['documents'][0]['content'].encode()).hexdigest()
    path.write_text(json.dumps(corpus), encoding='utf-8')
    assert service.retrieve_methodology('zznewuniquetoken')['has_matches'] is True


def test_rag_preserves_hospital_context_and_is_registered():
    from app.tools.agent_tools import search_methodology_documents, HOSPITAL_AGENT_TOOLS
    result = search_methodology_documents.invoke({'query': 'population HPSA', 'limit': 1})
    assert len(result['passages']) == 1
    assert extract_facility(result) == (None, False)
    assert search_methodology_documents in HOSPITAL_AGENT_TOOLS
