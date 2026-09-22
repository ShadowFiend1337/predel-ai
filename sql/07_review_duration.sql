-- Цель: оценить время от отправки до регистрации проверки куратором.
-- Результат: число измерений, среднее, медиана и P90, единица — часы.
-- Показатель включает очередь и не равен активному времени работы куратора.
-- Даты заранее приведены к одной временной зоне; пропуски и отрицательные интервалы исключены.
WITH durations AS (
    SELECT
        task_number,
        EXTRACT(
            EPOCH FROM (
                curator_reviewed_at - sent_to_review_at
            )
        ) / 3600.0 AS hours_to_review
    FROM pg_temp.checks
    WHERE sent_to_review_at IS NOT NULL
      AND curator_reviewed_at IS NOT NULL
      AND curator_reviewed_at >= sent_to_review_at
)
SELECT
    task_number,
    COUNT(*) AS measured_answers,
    ROUND(AVG(hours_to_review), 2) AS average_hours,
    ROUND(
        (
            PERCENTILE_CONT(0.5)
            WITHIN GROUP (ORDER BY hours_to_review)
        )::numeric,
        2
    ) AS median_hours,
    ROUND(
        (
            PERCENTILE_CONT(0.9)
            WITHIN GROUP (ORDER BY hours_to_review)
        )::numeric,
        2
    ) AS p90_hours
FROM durations
GROUP BY task_number
ORDER BY task_number NULLS LAST;
