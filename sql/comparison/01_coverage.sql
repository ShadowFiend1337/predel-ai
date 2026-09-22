-- Цель: показать полноту данных по типам заданий, сохранив все работы.
-- LEFT JOIN не теряет строки без оценки. Составные PK предотвращают размножение.
-- Пропуск означает отсутствие оценки в снимке; причина по таблице неизвестна.
SELECT
    w.task_number,
    COUNT(*) AS total_works,
    COUNT(r.score) AS with_reference,
    COUNT(p.score) AS with_predel,
    COUNT(t.score) AS with_their,
    COUNT(*) FILTER (
        WHERE r.score IS NOT NULL AND p.score IS NOT NULL AND t.score IS NOT NULL
    ) AS paired_works
FROM pg_temp.benchmark_works w
LEFT JOIN pg_temp.benchmark_references r
    ON r.work_id = w.work_id AND r.reference_kind = 'team'
LEFT JOIN pg_temp.benchmark_scores p
    ON p.work_id = w.work_id AND p.run_key = 'predel'
LEFT JOIN pg_temp.benchmark_scores t
    ON t.work_id = w.work_id AND t.run_key = 'their'
GROUP BY w.task_number
ORDER BY w.task_number;
