-- Цель: сравнить балл ИИ с принятым эталоном curator_points.
-- Результат: число сравнений, совпадений, точность в процентах и MAE в баллах.
-- Участвуют только две числовые оценки в допустимом диапазоне.
-- Пропуски дат не мешают сравнению. Точность замечаний этим не измеряется.
SELECT
    task_number,
    COUNT(*) AS compared_answers,
    COUNT(*) FILTER (
        WHERE ai_points = curator_points
    ) AS exact_matches,
    ROUND(
        100.0 * COUNT(*) FILTER (
            WHERE ai_points = curator_points
        ) / NULLIF(COUNT(*), 0),
        2
    ) AS accuracy_pct,
    ROUND(
        AVG(ABS(ai_points - curator_points)),
        2
    ) AS mean_absolute_error
FROM pg_temp.checks
WHERE max_points > 0
  AND ai_points BETWEEN 0 AND max_points
  AND curator_points BETWEEN 0 AND max_points
GROUP BY task_number
ORDER BY task_number NULLS LAST;
