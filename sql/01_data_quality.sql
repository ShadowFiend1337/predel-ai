-- Цель: найти пропуски, недопустимые баллы и ошибки времени.
-- Результат: строки для проверки; пропуск даты не исключает сравнение баллов.
-- Неразобранная дата сохраняется в *_raw, подготовленное значение равно NULL.
SELECT
    source_row,
    answer_id,
    task_number,
    ai_points,
    curator_points,
    max_points,
    sent_to_review_at,
    curator_reviewed_at,
    sent_to_review_at_raw,
    curator_reviewed_at_raw
FROM pg_temp.checks
WHERE NULLIF(BTRIM(answer_id), '') IS NULL
   OR NULLIF(BTRIM(task_id), '') IS NULL
   OR task_number IS NULL
   OR max_points IS NULL
   OR max_points <= 0
   OR ai_points IS NULL
   OR curator_points IS NULL
   OR ai_points NOT BETWEEN 0 AND max_points
   OR curator_points NOT BETWEEN 0 AND max_points
   OR sent_to_review_at IS NULL
   OR curator_reviewed_at IS NULL
   OR curator_reviewed_at < sent_to_review_at
ORDER BY source_row NULLS LAST, answer_id;
