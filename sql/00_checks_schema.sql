-- Учебная таблица PostgreSQL для семи аналитических запросов.
-- Выполнить в отдельном подключении; таблица существует только в этой сессии.
-- Это подготовленный аналитический слой, а не таблица приложения Predel.
-- Отсутствие PK и ограничений баллов намеренно: запросы 01/02 выявляют дефекты.
CREATE TEMP TABLE checks (
    source_row integer,
    answer_id text,
    ai_check_id text,
    task_id text,
    question_id text,
    task_number integer,
    stud_id text,
    max_points numeric,
    ai_points numeric,
    curator_points numeric,
    ai_comment text,
    curator_comment text,
    sent_to_review_at timestamp,
    curator_reviewed_at timestamp,
    sent_to_review_at_raw text,
    curator_reviewed_at_raw text
);
