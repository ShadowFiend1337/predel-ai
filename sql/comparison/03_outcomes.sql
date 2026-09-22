-- Цель: определить, какая система ближе к эталону на каждой сравнимой работе.
-- Итог содержит только агрегаты; предметные причины ошибок не устанавливает.
-- Одинаковая ошибка по модулю может иметь противоположный знак.
WITH classified AS (
    SELECT CASE
        WHEN p.score = r.score AND t.score = r.score THEN 'Обе системы точны'
        WHEN ABS(p.score - r.score) < ABS(t.score - r.score) THEN 'PredelAI ближе к эталону'
        WHEN ABS(p.score - r.score) > ABS(t.score - r.score) THEN 'Их модель ближе к эталону'
        ELSE 'Одинаковая ошибка по модулю'
    END AS result
    FROM pg_temp.benchmark_references r
    JOIN pg_temp.benchmark_scores p ON p.work_id = r.work_id AND p.run_key = 'predel'
    JOIN pg_temp.benchmark_scores t ON t.work_id = r.work_id AND t.run_key = 'their'
    WHERE r.reference_kind = 'team'
)
SELECT result, COUNT(*) AS works,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS share_pct
FROM classified
GROUP BY result
ORDER BY works DESC, result;
