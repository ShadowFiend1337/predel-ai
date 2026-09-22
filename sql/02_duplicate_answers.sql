-- Цель: выявить повторный учёт одной работы.
-- Результат: answer_id и количество строк с этим ID.
-- Повтор не удаляется автоматически: это может быть отдельная проверка ответа.
SELECT
    answer_id,
    COUNT(*) AS rows_count
FROM pg_temp.checks
WHERE NULLIF(BTRIM(answer_id), '') IS NOT NULL
GROUP BY answer_id
HAVING COUNT(*) > 1
ORDER BY rows_count DESC, answer_id;
