-- Цель: сравнить два продукта на одних работах и одном эталоне команды.
-- INNER JOIN оставляет только строки с обеими оценками и true_score.
-- task_number = NULL обозначает общий итог ROLLUP, а не неизвестное задание.
WITH paired AS (
    SELECT w.work_id, w.task_number, r.score AS reference_score,
           p.score AS predel_score, t.score AS their_score
    FROM pg_temp.benchmark_works w
    JOIN pg_temp.benchmark_references r
        ON r.work_id = w.work_id AND r.reference_kind = 'team'
    JOIN pg_temp.benchmark_scores p
        ON p.work_id = w.work_id AND p.run_key = 'predel'
    JOIN pg_temp.benchmark_scores t
        ON t.work_id = w.work_id AND t.run_key = 'their'
), scores AS (
    SELECT task_number, reference_score, 'predel' AS run_key, predel_score AS score FROM paired
    UNION ALL
    SELECT task_number, reference_score, 'their', their_score FROM paired
)
SELECT s.task_number, m.model_name,
       COUNT(*) AS works,
       COUNT(*) FILTER (WHERE s.score = s.reference_score) AS exact_matches,
       ROUND(100.0 * COUNT(*) FILTER (WHERE s.score = s.reference_score)
             / NULLIF(COUNT(*), 0), 2) AS accuracy_pct,
       ROUND(AVG(ABS(s.score - s.reference_score)), 3) AS mae
FROM scores s
JOIN pg_temp.benchmark_runs m ON m.run_key = s.run_key
GROUP BY m.model_name, ROLLUP(s.task_number)
ORDER BY s.task_number NULLS FIRST, m.model_name;
