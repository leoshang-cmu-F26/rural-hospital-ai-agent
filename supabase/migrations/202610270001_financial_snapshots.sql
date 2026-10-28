-- Private schema: hospital source data is accessed by the Python backend only.
CREATE SCHEMA IF NOT EXISTS hospital_data;
REVOKE ALL ON SCHEMA hospital_data FROM PUBLIC;

CREATE TABLE IF NOT EXISTS hospital_data.financial_import_runs (
    id uuid PRIMARY KEY,
    state text NOT NULL CHECK (state ~ '^[A-Z]{2}$'),
    dataset_year integer NOT NULL CHECK (dataset_year >= 2011),
    dataset_id text NOT NULL,
    source_url text NOT NULL,
    catalog_modified text,
    source_sha256 text,
    source_retrieved_at timestamptz,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    status text NOT NULL CHECK (status IN ('running', 'complete', 'failed')),
    national_row_count integer,
    state_row_count integer,
    national_inventory jsonb,
    error_code text
);

CREATE TABLE IF NOT EXISTS hospital_data.financial_report_rows (
    run_id uuid NOT NULL REFERENCES hospital_data.financial_import_runs(id),
    source_row_number integer NOT NULL,
    facility_id text NOT NULL,
    fiscal_year_begin text,
    fiscal_year_end text,
    raw_record jsonb NOT NULL,
    PRIMARY KEY (run_id, source_row_number)
);

CREATE INDEX IF NOT EXISTS financial_report_ccn_idx
    ON hospital_data.financial_report_rows (facility_id, run_id);

-- Only a completely validated run may replace the active state/year snapshot.
CREATE TABLE IF NOT EXISTS hospital_data.financial_coverage (
    state text NOT NULL,
    dataset_year integer NOT NULL,
    active_run_id uuid NOT NULL REFERENCES hospital_data.financial_import_runs(id),
    PRIMARY KEY (state, dataset_year)
);

CREATE INDEX IF NOT EXISTS financial_runs_year_status_idx
    ON hospital_data.financial_import_runs (dataset_year, status);
REVOKE ALL ON ALL TABLES IN SCHEMA hospital_data FROM PUBLIC;
