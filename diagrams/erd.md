# Модель данных

## Реализация: фрагмент физической модели

```mermaid
erDiagram
    USER |o--o{ ATTEMPT : "внешний ключ user_id"
    TASK_CATALOG ||..o{ ATTEMPT : "логическая связь без FK"
    USER {
        string id PK
    }
    TASK_CATALOG {
        string id PK
        text statement_md
        text reference_solution_md
        string name
        string theme_title
        string source
    }
    ATTEMPT {
        string id PK
        string task_id "NOT NULL, индекс, без FK"
        string user_id FK "NULL допустим"
        text text
        string file "NULL допустим, имя файла при отправке"
        json feedback "NULL допустим"
        float score "NULL допустим"
        string mode
        integer time_spent_sec "NULL допустим"
        boolean is_solved
        json pipeline_artifacts "NULL допустим"
        datetime created_at
    }
```

Пунктирная связь с каталогом описывает ожидаемую предметную принадлежность, а не гарантированную ссылочную целостность БД. `user_id` допускает NULL; обязательная аутентификация текущего API не делает физическую колонку NOT NULL. `String` не обеспечивает проверку формата UUID.

`solution_text` публичного API соответствует `Attempt.text`. Пути исходных файлов находятся в `pipeline_artifacts.uploads[].storage_path`. В `Attempt.file` текущий обработчик отправки сохраняет имя или объединённые имена. `updated_at` отсутствует, `max_score` хранится внутри `feedback`. [Словарь и сопоставление полей](../docs/17_glossary_and_data_dictionary.md).

## Целевая логическая модель сайта: API 2.0

Эта модель обеспечивает C-11 и расширение А7 в [UC-01](../docs/03_use_case_text_submission.md). Она проектируется отдельно от действующей таблицы `Attempt` и интеграционных заданий LMS. Названия сущностей логические; миграции БД и SQL на этом этапе не создаются.

```mermaid
erDiagram
    USER ||--o{ ATTEMPT_V2 : "отправляет"
    TASK_CATALOG ||--o{ ATTEMPT_V2 : "задаёт условие"
    ATTEMPT_V2 ||--o| ATTEMPT_REVIEW : "требует"
    USER |o--o{ ATTEMPT_REVIEW : "назначен куратором"
    ATTEMPT_REVIEW ||--|{ ATTEMPT_REVIEW_EVENT : "сохраняет историю"
    USER |o--o{ ATTEMPT_REVIEW_EVENT : "выполнил действие"
    ATTEMPT_V2 {
        string id PK
        string user_id FK "NOT NULL"
        string task_id FK "NOT NULL"
        text source_text "исходник, не изменяется"
        text prepared_text "NULL допустим"
        float max_score_snapshot "больше нуля"
        json task_snapshot "условие, критерии и версии"
        json automatic_result "первоначальный результат"
        json final_result "NULL до утверждения"
        json pipeline_artifacts "основания проверки"
        string result_status "final или provisional"
        string schema_version "2.0"
        integer version
        datetime created_at
    }
    ATTEMPT_REVIEW {
        string id PK
        string attempt_id FK, UK
        string assigned_to FK "NULL до назначения"
        string status "pending, in_progress, completed"
        json reason_codes "непустой массив"
        float curator_score "NULL до завершения"
        string decision "NULL до завершения"
        text reason_text "обязательно при изменении оценки"
        integer version
        datetime created_at
        datetime completed_at "NULL до завершения"
    }
    ATTEMPT_REVIEW_EVENT {
        string id PK
        string review_id FK
        string event_id UK
        string actor_id FK "NULL для системы"
        string from_status "NULL при создании"
        string to_status
        text reason_text
        integer version
        datetime occurred_at
    }
```

### Ограничения и отображение в API

- У каждой попытки есть владелец и задача. Автор запроса определяется токеном; доступ к истории фильтруется по владельцу на сервере.
- `source_text` содержит исходный текст до преобразований; `prepared_text` — отдельное представление для обработки. Снимок условия, критериев, их версий и максимума сохраняет основания оценки после изменения каталога.
- `automatic_result` сохраняет первоначальные пояснения, источник, причины и балл, в том числе `null`, если числовой оценки нет. Ручная проверка его не перезаписывает. Для автоматического окончательного решения `final_result` совпадает с принятым автоматическим результатом; после куратора содержит утверждённый результат.
- `UNIQUE(attempt_id)` допускает не более одной задачи куратора на попытку в первой версии. Предварительная попытка, задача со статусом `pending` и событие её создания сохраняются одной транзакцией до HTTP 200. Автоматическая окончательная попытка задачи куратора не требует.
- При назначении заполняется `assigned_to`, статус становится `in_progress`; назначать можно только уполномоченного пользователя. При снятии назначения статус возвращается в `pending`, назначение очищается, причина записывается в историю.
- При завершении обязательны автор, время, числовой балл в пределах снимка максимума и решение `confirmed` либо `overridden`. Для изменения балла или пояснений обязательна причина. Если автоматического балла не было, решение считается `overridden` с причиной отсутствия автоматической оценки.
- Завершение ручной проверки атомарно сохраняет `final_result`, переводит попытку в `final`, задачу в `completed` и добавляет событие. Ожидаемая `version` защищает от перезаписи конкурентным действием; повтор `event_id` не создаёт второй переход. Завершённую задачу не открывают повторно в этой версии.
- Состояние и история ручной проверки изменяются вместе. Автоматическое каскадное удаление аудита не предполагается; сроки хранения согласуются отдельно.

| Публичное поле C-11 | Источник в целевой модели |
|---|---|
| `id`, `task_id`, `created_at` | `AttemptV2.id`, `task_id`, `created_at` |
| `solution_text` | `AttemptV2.source_text` |
| `max_score` | `AttemptV2.max_score_snapshot` |
| `result_status` | `AttemptV2.result_status` |
| `score`, `feedback`, `decision` | `final_result` при `final`, иначе `automatic_result` |
| `is_solved` | Вычисляется: `final` и балл равен максимуму; отдельно в логической модели не хранится |
| `review.id`, `review.status` | Связанная `AttemptReview`; `null`, если автоматический результат окончательный |

Гарантия существования `review.id` требует реализации этой связи и транзакции. Проверенная форма JSON не доказывает сохранение записи. [Описание API](../docs/11_api_specification.md), [протокол и границы проверки](../docs/12_api_verification_protocol.md).

## Целевая логическая модель LMS и ручной проверки

```mermaid
erDiagram
    LMS_CLIENT ||--o{ CHECK_JOB : "создаёт"
    TASK_CATALOG ||--o{ CHECK_JOB : "проверяется"
    CHECK_JOB ||--o{ LAYER_RESULT : "содержит"
    CHECK_JOB ||--o| CURATOR_REVIEW : "требует"
    CURATOR |o--o{ CURATOR_REVIEW : "назначен"
    CHECK_JOB ||--o{ STATUS_HISTORY : "изменяет состояние"
    CHECK_JOB ||--o{ OUTBOX_EVENT : "создаёт событие"
    LMS_CLIENT {
        string id PK
        string name
    }
    TASK_CATALOG {
        string id PK
    }
    CURATOR {
        string id PK
    }
    CHECK_JOB {
        string id PK
        string lms_client_id FK
        string task_id FK
        string external_submission_id "необязательно"
        string idempotency_key
        string request_hash
        json submission
        string status
        json automatic_result "NULL допустим"
        json final_result "NULL допустим"
        json error "NULL допустим"
        string schema_version
        integer version
        datetime created_at
        datetime updated_at
    }
    LAYER_RESULT {
        string id PK
        string check_id FK
        string layer
        integer execution_attempt
        string status
        json result "NULL допустим"
        json error "NULL допустим"
        datetime started_at "NULL до запуска"
        datetime completed_at "NULL до завершения"
        integer latency_ms "NULL до завершения"
        string schema_version
    }
    CURATOR_REVIEW {
        string id PK
        string check_id FK, UK
        string assigned_to FK "NULL до назначения"
        string status
        float automatic_score "NULL допустим"
        float curator_score "NULL до завершения"
        string decision "NULL до завершения"
        string reason_code "обязательно при изменении"
        text reason_text
        integer version
        datetime completed_at "NULL до завершения"
    }
    STATUS_HISTORY {
        string id PK
        string check_id FK
        string event_id UK
        string from_status
        string to_status
        string actor_type
        string actor_id "NULL для системного события"
        integer version
        string reason_code "обязателен при снятии назначения"
        text reason_text "NULL допустим"
        datetime changed_at
    }
    OUTBOX_EVENT {
        string id PK
        string check_id FK
        string event_type
        json payload
        datetime published_at "NULL до доставки"
        datetime created_at
    }
```

## Ограничения целевой модели

- `UNIQUE(lms_client_id, idempotency_key)` защищает создание проверки; `request_hash` выявляет повтор ключа с другим телом.
- `UNIQUE(check_id, layer, execution_attempt)` различает исполнения этапа и блокирует дубли одного исполнения.
- `CuratorReview.check_id` уникален: в первой версии не более одной ручной проверки на задание.
- `assigned_to` связывается с уполномоченным куратором. При снятии назначения запись возвращается в `pending`.
- `decision` принимает `confirmed` или `overridden`; при завершении обязательны оценка, автор и время. При отсутствии автоматической оценки новое ручное решение считается `overridden` с причиной `NO_AUTOMATIC_SCORE`.
- Баллы находятся в диапазоне задачи; `null` означает отсутствие оценки, а не ноль. Межтабличные проверки диапазона выполняет приложение либо согласованный механизм БД.
- `version` обеспечивает проверку конкурентных изменений; история хранит новую версию каждого перехода. `event_id` обеспечивает дедупликацию переходов. При снятии назначения куратору обязательна причина в истории.
- Автоматический и окончательный результаты хранятся раздельно. При автоматическом принятии окончательный результат соответствует автоматическому; после куратора — ручному.
- Задание и исходящее событие сохраняются одной транзакцией. Подтверждение доставки не удаляет историю обработки.
- Пока проверка активна, связанные записи и исходная работа не удаляются. Сроки хранения завершённых проверок и порядок удаления согласуются отдельно; автоматическое каскадное удаление аудита не предполагается.

Эта схема описывает проектируемые сущности и ограничения; она не является существующей схемой SQLite.
