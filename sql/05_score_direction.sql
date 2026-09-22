-- Цель: различить завышение, занижение и совпадение с эталонным баллом.
-- Результат: количество и доля каждой категории среди всех сравнимых работ.
-- Пустая сравнимая выборка даёт пустой результат, а не нулевую точность.
WITH comparisons AS (
    SELECT
        CASE
            WHEN ai_points > curator_points THEN 'Завышение'
            WHEN ai_points < curator_points THEN 'Занижение'
            ELSE 'Совпадение'
        END AS result
    FROM pg_temp.checks
    WHERE max_points > 0
      AND ai_points BETWEEN 0 AND max_points
      AND curator_points BETWEEN 0 AND max_points
)
SELECT
    result,
    COUNT(*) AS answers_count,
    ROUND(
        100.0 * COUNT(*) / SUM(COUNT(*)) OVER (),
        2
    ) AS share_pct
FROM comparisons
GROUP BY result
ORDER BY answers_count DESC, result;
