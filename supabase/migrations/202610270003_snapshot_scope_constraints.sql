-- Reconcile legacy coverage pointers with their own state/year's latest complete run.
UPDATE hospital_data.financial_coverage c
SET active_run_id = (
    SELECT i.id FROM hospital_data.financial_import_runs i
    WHERE i.state = c.state AND i.dataset_year = c.dataset_year AND i.status = 'complete'
    ORDER BY i.finished_at DESC LIMIT 1
)
WHERE EXISTS (
    SELECT 1 FROM hospital_data.financial_import_runs wrong
    WHERE wrong.id = c.active_run_id
      AND (wrong.state <> c.state OR wrong.dataset_year <> c.dataset_year)
);

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='financial_run_scope_unique'
        AND conrelid='hospital_data.financial_import_runs'::regclass) THEN
        ALTER TABLE hospital_data.financial_import_runs
            ADD CONSTRAINT financial_run_scope_unique UNIQUE(state, dataset_year, id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='financial_coverage_scope_fk'
        AND conrelid='hospital_data.financial_coverage'::regclass) THEN
        ALTER TABLE hospital_data.financial_coverage
            ADD CONSTRAINT financial_coverage_scope_fk FOREIGN KEY(state, dataset_year, active_run_id)
            REFERENCES hospital_data.financial_import_runs(state, dataset_year, id);
    END IF;
    IF to_regclass('hospital_data.reference_coverage') IS NOT NULL THEN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='reference_run_scope_unique'
            AND conrelid='hospital_data.reference_import_runs'::regclass) THEN
            ALTER TABLE hospital_data.reference_import_runs
                ADD CONSTRAINT reference_run_scope_unique UNIQUE(kind, state, id);
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='reference_coverage_scope_fk'
            AND conrelid='hospital_data.reference_coverage'::regclass) THEN
            ALTER TABLE hospital_data.reference_coverage
                ADD CONSTRAINT reference_coverage_scope_fk FOREIGN KEY(kind, state, active_run_id)
                REFERENCES hospital_data.reference_import_runs(kind, state, id);
        END IF;
    END IF;
END $$;
