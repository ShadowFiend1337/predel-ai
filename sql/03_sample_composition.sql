-- Цель: оценить состав и неравномерность выборки по номеру задания.
-- Результат: строки, разные задачи и ученики; ошибки баллов строки не исключают.
-- До интерпретации answers_count как числа работ нужно разрешить дубли из 02.
-- Уникальных учеников разных групп нельзя складывать без проверки пересечения.
SELECT
    task_number,
    COUNT(*) AS answers_count,
    COUNT(DISTINCT task_id) AS tasks_count,
    COUNT(DISTINCT stud_id) AS students_count
FROM pg_temp.checks
GROUP BY task_number
ORDER BY task_number NULLS LAST;
