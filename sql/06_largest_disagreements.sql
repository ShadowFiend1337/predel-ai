-- Цель: отобрать по три сильных расхождения каждого номера задания для разбора.
-- Результат: работа, баллы, разница и комментарии обеих сторон.
-- Причина ошибки определяется экспертом, а не этим ранжированием.
WITH ranked AS (
    SELECT
        source_row,
        answer_id,
        task_number,
        ai_points,
        curator_points,
        ABS(ai_points - curator_points) AS score_difference,
        ai_comment,
        curator_comment,
        ROW_NUMBER() OVER (
            PARTITION BY task_number
            ORDER BY
                ABS(ai_points - curator_points) DESC,
                answer_id,
                source_row
        ) AS position
    FROM pg_temp.checks
    WHERE max_points > 0
      AND ai_points BETWEEN 0 AND max_points
      AND curator_points BETWEEN 0 AND max_points
      AND ai_points <> curator_points
)
SELECT
    source_row,
    answer_id,
    task_number,
    ai_points,
    curator_points,
    score_difference,
    ai_comment,
    curator_comment
FROM ranked
WHERE position <= 3
ORDER BY task_number NULLS LAST, position;
