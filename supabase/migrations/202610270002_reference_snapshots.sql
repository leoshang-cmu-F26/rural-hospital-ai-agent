-- Access evidence stays separate from historical fiscal reports and keeps as-of dates.
CREATE TABLE IF NOT EXISTS hospital_data.reference_import_runs (
    id uuid PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('hospital_directory', 'county_demographics', 'primary_care_hpsa', 'hospital_coordinates')),
    state text NOT NULL,
    source_url text NOT NULL,
    source_year integer,
    retrieved_at timestamptz NOT NULL,
    finished_at timestamptz NOT NULL DEFAULT now(),
    status text NOT NULL CHECK (status IN ('complete', 'partial')),
    row_count integer NOT NULL,
    available_count integer NOT NULL,
    payload_sha256 text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS hospital_data.reference_records (
    run_id uuid NOT NULL REFERENCES hospital_data.reference_import_runs(id),
    record_key text NOT NULL,
    payload jsonb NOT NULL,
    PRIMARY KEY (run_id, record_key)
);
CREATE INDEX IF NOT EXISTS reference_record_key_idx ON hospital_data.reference_records (record_key, run_id);
CREATE TABLE IF NOT EXISTS hospital_data.reference_coverage (
    kind text NOT NULL,
    state text NOT NULL,
    active_run_id uuid NOT NULL REFERENCES hospital_data.reference_import_runs(id),
    PRIMARY KEY (kind, state)
);
REVOKE ALL ON ALL TABLES IN SCHEMA hospital_data FROM PUBLIC;
