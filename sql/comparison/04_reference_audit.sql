-- Цель: показать расхождения между исходной оценкой куратора и эталоном команды.
-- Это контроль происхождения эталона, а не сравнение моделей с куратором.
SELECT COUNT(*) AS compared_references,
       COUNT(*) FILTER (WHERE team.score <> curator.score) AS different_scores
FROM pg_temp.benchmark_references team
JOIN pg_temp.benchmark_references curator ON curator.work_id = team.work_id
    AND curator.reference_kind = 'curator'
WHERE team.reference_kind = 'team';
