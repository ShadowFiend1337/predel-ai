-- Аналитическая модель одного снимка; все таблицы временные.
-- work_id назначается при импорте и уникален только внутри снимка.
CREATE TEMP TABLE benchmark_works (
    work_id integer PRIMARY KEY,
    task_number integer NOT NULL,
    original_row_id text
);

-- Это две серии оценок из столбцов источника, а не журнал реальных запусков.
CREATE TEMP TABLE benchmark_runs (
    run_key text PRIMARY KEY,
    model_name text NOT NULL,
    model_version text,
    evaluated_at timestamp
);

CREATE TEMP TABLE benchmark_scores (
    work_id integer REFERENCES benchmark_works(work_id),
    run_key text REFERENCES benchmark_runs(run_key),
    score numeric NOT NULL CHECK (score >= 0),
    PRIMARY KEY (work_id, run_key)
);

CREATE TEMP TABLE benchmark_references (
    work_id integer REFERENCES benchmark_works(work_id),
    reference_kind text CHECK (reference_kind IN ('team', 'curator')),
    score numeric NOT NULL CHECK (score >= 0),
    PRIMARY KEY (work_id, reference_kind)
);

INSERT INTO benchmark_runs (run_key, model_name) VALUES
    ('predel', 'PredelAI'),
    ('their', 'Стобалльный репетитор');
