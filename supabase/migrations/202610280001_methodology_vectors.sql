-- Private, versioned methodology vectors; no browser-facing database privileges.
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
CREATE TABLE IF NOT EXISTS hospital_data.methodology_corpora (
    id uuid PRIMARY KEY,
    fingerprint text NOT NULL UNIQUE,
    corpus_sha256 text NOT NULL,
    embedding_model text NOT NULL,
    embedding_dimensions integer NOT NULL CHECK (embedding_dimensions = 1536),
    passage_count integer NOT NULL CHECK (passage_count > 0),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS hospital_data.methodology_passages (
    corpus_id uuid NOT NULL REFERENCES hospital_data.methodology_corpora(id),
    passage_id text NOT NULL,
    excerpt text NOT NULL,
    source_metadata jsonb NOT NULL,
    embedding_input_sha256 text NOT NULL,
    embedding extensions.vector(1536) NOT NULL,
    PRIMARY KEY (corpus_id, passage_id)
);
CREATE INDEX IF NOT EXISTS methodology_embedding_input_idx
    ON hospital_data.methodology_passages(embedding_input_sha256);
CREATE TABLE IF NOT EXISTS hospital_data.methodology_active (
    name text PRIMARY KEY CHECK (name = 'methodology'),
    corpus_id uuid NOT NULL REFERENCES hospital_data.methodology_corpora(id)
);
REVOKE ALL ON hospital_data.methodology_corpora,
    hospital_data.methodology_passages, hospital_data.methodology_active FROM PUBLIC;
