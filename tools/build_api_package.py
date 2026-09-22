"""Собрать OpenAPI и коллекции Postman для UC-01. Используются модели backend."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml
from fastapi import APIRouter, FastAPI

from uc01_stand import CASE_ROOT, SOLUTION, TASK_ID, attempts, submit
from app.api.schemas.attempt import AttemptOut, Feedback
from target_contract_models import AttemptV2, ErrorV2, SubmitTextV2

REF = "#/components/schemas/"
POSTMAN_SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def response(schema, description, examples=None):
    content = {"schema": schema}
    if examples:
        content["examples"] = {name: {"value": value} for name, value in examples.items()}
    return {"description": description, "content": {"application/json": content}}


def ref(name):
    return {"$ref": REF + name}


def current_examples():
    base = dict(id="attempt-demo-final", task_id=TASK_ID, solution_text=SOLUTION,
                created_at="2026-09-15T12:00:00Z", score=2, max_score=2, is_solved=True)
    final = AttemptOut(**base, feedback=Feedback(checked=True, score=2, max_score=2,
        general_comment="Решение соответствует критериям.", final_decision="AUTO_ACCEPT")).model_dump(mode="json")
    provisional = copy.deepcopy(final)
    provisional.update(id="attempt-demo-review", score=1, is_solved=False, needs_curator=True,
                       review_reason="Оценщик B недоступен")
    provisional["feedback"].update(score=1, needs_curator=True, review_required=True,
        review_reason="Оценщик B недоступен", general_comment="Оценщик B недоступен",
        final_decision="MANUAL_REVIEW_REQUIRED")
    failure = copy.deepcopy(provisional)
    failure.update(id="attempt-demo-failure", score=0, review_reason="Проверка завершилась с ошибкой")
    failure["feedback"].update(score=0, general_comment="Проверка завершилась с ошибкой. Решение отправлено на ручную проверку.",
                               review_reason="Проверка завершилась с ошибкой")
    answer = copy.deepcopy(final)
    answer.update(id="attempt-demo-answer", solution_text="Ответ: 1", score=None, max_score=None, is_solved=False)
    answer["feedback"].update(score=0, final_decision=None, general_comment="Нужен полный ход решения: один итоговый ответ не засчитывается.")
    return {"окончательная": final, "признак_куратора": provisional, "отказ_оценивания": failure, "только_ответ": answer}


def target_examples():
    final = dict(schema_version="2.0", id="attempt-v2-demo", task_id=TASK_ID,
        solution_text=SOLUTION, created_at="2026-09-15T12:00:00Z", max_score=2,
        feedback={"general_comment": "Решение соответствует критериям.", "comments": []},
        decision={"source": "primary_agreement", "reason_codes": []},
        result_status="final", score=2, is_solved=True, review=None)
    provisional = copy.deepcopy(final)
    provisional.update(id="attempt-v2-review", result_status="provisional", score=1, is_solved=False,
                       review={"id": "review-demo", "status": "pending"})
    provisional["decision"] = {"source": "grader_a", "reason_codes": ["GRADER_UNAVAILABLE"]}
    provisional["feedback"]["general_comment"] = "Оценка предварительная. Задача передана куратору."
    no_score = copy.deepcopy(provisional)
    no_score.update(score=None)
    no_score["decision"] = {"source": "none", "reason_codes": ["INSUFFICIENT_EVIDENCE"]}
    reviewed = copy.deepcopy(final)
    reviewed.update(id="attempt-v2-reviewed", review={"id": "review-completed", "status": "completed"})
    reviewed["decision"] = {"source": "curator", "reason_codes": ["CONFIRMED"]}
    return {"окончательная": final, "предварительная": provisional, "без_предварительного_балла": no_score,
            "подтверждена_куратором": reviewed}


def error_example(code, message, retryable=False):
    return {"schema_version": "2.0", "request_id": "request-demo", "result": None,
            "error": {"code": code, "message": message, "retryable": retryable}}


def build_current():
    app = FastAPI(title="PredelAI — действующий API сценария UC-01", version="0.3.3-case.1")
    selected = [r for r in submit.router.routes if r.path == "/submit"]
    selected += [r for r in attempts.router.routes if r.path == "/tasks/{task_id}/attempts"]
    app.include_router(APIRouter(routes=selected), prefix="/api")
    spec = app.openapi()
    spec["info"]["description"] = "Срез двух действующих операций приложения 0.3.3. Схемы извлечены из FastAPI; описания и ошибочные ответы дополнены по коду. Технический отказ может возвращаться как 200 с нулём и признаком куратора; это ограничение реализации. Синтетические примеры не являются результатами работы моделей."
    spec["servers"] = [{"url": "http://127.0.0.1:8765", "description": "Изолированный стенд из tools/uc01_stand.py"},
                       {"url": "http://localhost:8000", "description": "Пример адреса локального backend; проверить фактический порт"}]
    schemas = spec["components"]["schemas"]
    schemas["DetailError"] = {"type": "object", "required": ["detail"], "properties": {"detail": {"type": "string"}}}
    schemas["DomainError"] = {"type": "object", "required": ["error"], "properties": {"error": {"type": "string"}}}
    schemas["ValidationProblem"] = {"oneOf": [ref("DetailError"), ref("HTTPValidationError")]}
    spec["components"]["securitySchemes"]["HTTPBearer"].update(bearerFormat="JWT", description="Токен доступа в Authorization: Bearer. Refresh-токен не принимается.")
    example = current_examples()
    post = spec["paths"]["/api/submit"]["post"]
    post.update(summary="Отправить решение текстом", description="UC-01. task_id — ID каталога. text должен содержать непробельный символ. Верхний предел не проверяется схемой: обработчик обрезает текст по настройке, по умолчанию до 40 000 символов. Неизвестные поля тела игнорируются. Ограничитель: 20 запросов/60 секунд на пользователя и IP в одном процессе; администратор освобождён. Идемпотентность не гарантируется.", tags=["Решения"])
    post["requestBody"]["content"]["application/json"]["example"] = {"task_id": TASK_ID, "text": SOLUTION}
    post["responses"]["200"] = response(ref("AttemptOut"), "Попытка сохранена; ответ может содержать признак ручной проверки или технический ноль.", example)
    post["responses"]["429"] = response(ref("DetailError"), "Превышена частота. Retry-After текущим ограничителем не задаётся.", {"лимит": {"detail": "Rate limit exceeded for submit"}})
    get = spec["paths"]["/api/tasks/{task_id}/attempts"]["get"]
    get.update(summary="Получить свои попытки по задаче", description="Только попытки текущего пользователя. Чужие попытки не включаются в список; пустой список — 200. Неизвестная задача — 404. limit 1–200 (50), offset ≥ 0 (0). Текущий репозиторий возвращает новые записи первыми; total и курсор не возвращаются. max_score истории извлекается из feedback и может отличаться от верхнего поля первоначального ответа в ветви «только ответ».", tags=["История"])
    get["responses"]["200"] = response({"type": "array", "items": ref("AttemptOut")}, "Массив собственных попыток.", {"список": [example["окончательная"]], "пусто": []})
    for op in [post, get]:
        op["responses"]["401"] = response(ref("DetailError"), "Авторизация отсутствует или недействительна.", {"нет_токена": {"detail": "Auth required"}})
        op["responses"]["404"] = response(ref("DetailError"), "Задача отсутствует.", {"нет_задачи": {"detail": "Task not found"}})
        op["responses"]["422"] = response(ref("ValidationProblem"), "Неверные поля, параметры либо непригодный текст.", {"пусто": {"detail": "Solution text is empty"}, "схема": {"detail": [{"loc": ["body", "text"], "msg": "Field required", "type": "missing"}]}})
        op["responses"]["400"] = response(ref("DomainError"), "Общий обработчик DomainError, если зависимость завершилась доменной ошибкой.")
        op["responses"]["500"] = {"description": "Необработанная ошибка, в том числе ошибка хранилища; единый JSON-контракт не задан.", "content": {"text/plain": {"schema": {"type": "string"}, "example": "Internal Server Error"}}}
    get["responses"]["422"] = response(ref("HTTPValidationError"), "Недопустимые параметры истории.", {"параметр": {"detail": [{"loc": ["query", "limit"], "msg": "Input should be greater than or equal to 1", "type": "greater_than_equal"}]}})
    spec["tags"] = [{"name": "Решения"}, {"name": "История"}]
    return spec


def build_target():
    schemas = {}
    for model in [SubmitTextV2, AttemptV2, ErrorV2]:
        schema = model.model_json_schema(mode="serialization", ref_template=REF + "{model}")
        schemas.update(schema.pop("$defs", {}))
        schemas[model.__name__] = schema
    examples = target_examples()
    for value in examples.values():
        AttemptV2.model_validate_json(json.dumps(value))
    spec = {"openapi": "3.1.0", "info": {"title": "PredelAI — целевой API UC-01", "version": "2.0.0-draft",
        "description": "Проектный контракт, в backend не реализован. Новые маршруты /api/v2 сохраняют совместимость существующих /api. Балл хранится в ответе один раз; окончательность и ссылка на задачу куратора явные. Числовой балл при техническом отказе отсутствует. Внешний LMS API /checks сюда не входит."},
        "servers": [{"url": "https://api.example.invalid", "description": "Адрес-заполнитель; заменить адресом реализации v2"}],
        "security": [{"BearerAuth": []}], "tags": [{"name": "Решения"}, {"name": "История"}],
        "paths": {}, "components": {"schemas": schemas, "securitySchemes": {"BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT", "description": "Токен доступа ученика; refresh-токен не принимается."}}}}
    errors = {
        "401": ("AUTH_REQUIRED", "Необходимо войти в систему.", False),
        "404": ("TASK_NOT_FOUND", "Задача не найдена.", False),
        "422": ("VALIDATION_ERROR", "Проверьте обязательные поля и длину решения.", False),
        "429": ("RATE_LIMITED", "Слишком много отправок. Повторите позже.", True),
        "500": ("PERSISTENCE_FAILURE", "Не удалось сохранить результат.", True),
        "503": ("GRADING_UNAVAILABLE", "Не удалось получить оценку. Повторите позже.", True),
    }
    responses = {}
    for status, (code, message, retryable) in errors.items():
        allowed = [code]
        extra = {}
        if status == "500":
            allowed.append("INTERNAL_ERROR")
            extra["неизвестный_исход"] = error_example("INTERNAL_ERROR", "Не удалось подтвердить результат запроса. Проверьте историю.")
        if status == "503":
            allowed.append("PERSISTENCE_OUTCOME_UNKNOWN")
            extra["неподтверждённая_фиксация"] = error_example("PERSISTENCE_OUTCOME_UNKNOWN", "Исход сохранения неизвестен. Проверьте историю перед повторной отправкой.")
        schema = {"allOf": [ref("ErrorV2"), {"type": "object", "properties": {"error": {"type": "object", "properties": {"code": {"enum": allowed}}}}}]}
        responses[status] = response(schema, message, {"пример": error_example(code, message, retryable), **extra})
    responses["429"]["headers"] = {"Retry-After": {"required": True, "description": "Секунды до разрешённой повторной отправки.", "schema": {"type": "integer", "minimum": 1}, "example": 60}}
    responses["200"] = response(ref("AttemptV2"), "Сохранён окончательный или предварительный результат. Предварительный ответ требует сохранённой задачи куратора.", {k: v for k, v in examples.items() if k != "подтверждена_куратором"})
    spec["paths"]["/api/v2/submit"] = {"post": {"operationId": "submitTextV2", "summary": "Отправить решение текстом", "tags": ["Решения"],
        "description": "Синхронная операция UC-01. Валидация до вызовов ИИ. Неизвестные поля отклоняются. text: 1–40 000 символов Unicode до нормализации, включая пробелы; нужен непробельный символ. Исходный текст сохраняется без математических замен. 200 — только после фиксации попытки и, если нужно, задачи куратора. Idempotency-Key не поддерживается; неизвестный исход требует проверки истории, автоматический повтор запрещён. Общий числовой предел времени согласуется отдельно по NFR-PERF-01.",
        "requestBody": {"required": True, "content": {"application/json": {"schema": ref("SubmitTextV2"), "example": {"task_id": TASK_ID, "text": SOLUTION}}}}, "responses": responses}}
    get_responses = {s: copy.deepcopy(responses[s]) for s in ["401", "404", "422", "500"]}
    get_responses["500"] = response(ref("ErrorV2"), "История временно недоступна.", {"ошибка": error_example("INTERNAL_ERROR", "Не удалось загрузить историю.", True)})
    get_responses["200"] = response({"type": "array", "items": ref("AttemptV2")}, "Собственные попытки, созданные по контракту 2.0. Старые записи доступны через действующий API.", {"история": [examples["окончательная"], examples["подтверждена_куратором"]], "пусто": []})
    spec["paths"]["/api/v2/tasks/{task_id}/attempts"] = {"get": {"operationId": "listMyAttemptsV2", "summary": "Получить свою историю версии 2.0", "tags": ["История"],
        "description": "Только записи авторизованного ученика для указанной задачи, в порядке created_at DESC, id DESC. limit/offset не обеспечивают неизменность страниц при конкурентных вставках. Чужие записи не раскрываются; задача без собственных попыток возвращает []. Это история, не API состояния выполняющегося запроса.",
        "parameters": [{"name": "task_id", "in": "path", "required": True, "schema": {"type": "string", "minLength": 1}},
                       {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}},
                       {"name": "offset", "in": "query", "schema": {"type": "integer", "minimum": 0, "default": 0}}], "responses": get_responses}}
    schemas["AttemptV2"]["x-invariants"] = ["0 <= score <= max_score, если score не null", "final: is_solved эквивалентен score == max_score", "provisional: is_solved=false, review.id существует, reason_codes непусты", "final с review: status=completed и source=curator; без review source != curator", "Числовой балл требует source != none"]
    return spec


def definitions(spec):
    return json.loads(json.dumps(spec["components"]["schemas"]).replace(REF, "#/definitions/"))


def request_item(name, method, path, *, body=None, status=200, schema=None, tests=None, auth=None, pre=None):
    req = {"method": method, "header": [], "url": "{{base_url}}" + path}
    if auth is not None:
        req["auth"] = auth
    if body is not None:
        req["header"] = [{"key": "Content-Type", "value": "application/json"}]
        req["body"] = {"mode": "raw", "raw": body if isinstance(body, str) else json.dumps(body, ensure_ascii=False, indent=2), "options": {"raw": {"language": "json"}}}
    lines = [f'pm.test("HTTP {status}", () => pm.response.to.have.status({status}));']
    if schema:
        normalized = json.loads(json.dumps(schema).replace(REF, "#/definitions/"))
        lines += ["const body = pm.response.json();", "const definitions = JSON.parse(pm.collectionVariables.get('schemas'));",
                  f"const schema = Object.assign({json.dumps(normalized)}, {{definitions}});",
                  "pm.test('Ответ соответствует схеме', () => pm.response.to.have.jsonSchema(schema));"]
    lines += tests or []
    item = {"name": name, "request": req, "event": [{"listen": "test", "script": {"type": "text/javascript", "exec": lines}}]}
    if pre:
        item["event"].insert(0, {"listen": "prerequest", "script": {"type": "text/javascript", "exec": pre}})
    return item


NOAUTH = {"type": "noauth"}


def bearer(variable):
    return {"type": "bearer", "bearer": [{"key": "token", "value": "{{" + variable + "}}", "type": "string"}]}


def collection_base(name, description, schemas, base_url):
    return {"info": {"name": name, "description": description, "schema": POSTMAN_SCHEMA}, "auth": bearer("token"),
        "variable": [{"key": "base_url", "value": base_url}, {"key": "token", "value": ""}, {"key": "other_token", "value": ""},
                     {"key": "task_id", "value": TASK_ID}, {"key": "schemas", "value": json.dumps(schemas, ensure_ascii=False)}], "item": []}


def build_current_collection(spec):
    col = collection_base("PredelAI · UC-01 · действующий API", "Восемь сценариев на изолированном стенде tools/uc01_stand.py. Контрольные /_demo/... существуют только на стенде. Реальные обработчики, JWT и ограничитель; хранилище и оценивание заменены. Запускать всю коллекцию по порядку. Проверка текущего поведения не означает выполнение целевых требований.", definitions(spec), "http://127.0.0.1:8765")
    col["event"] = [{"listen": "prerequest", "script": {"type": "text/javascript", "exec": ["const url = pm.variables.replaceIn('{{base_url}}');", r"if (!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(url)) { throw new Error('Эта коллекция предназначена только для локального учебного стенда'); }"]}}]
    col["item"].append(request_item("00 · Получить учебные токены", "POST", "/_demo/session", auth=NOAUTH,
        tests=["const sessionPayload = pm.response.json();", "pm.test('Изолированный стенд', () => pm.expect(sessionPayload.mode).to.eql('current_source_fixture'));", "pm.collectionVariables.set('token', sessionPayload.token);", "pm.collectionVariables.set('other_token', sessionPayload.other_token);"]))
    def reset(mode):
        return request_item("Подготовить изолированные данные", "POST", "/_demo/reset", body={"scenario": mode}, auth=NOAUTH)
    def state(attempts_count, calls):
        return request_item("Проверить побочные действия", "GET", "/_demo/state", auth=NOAUTH, tests=[f"pm.test('Сохранения и вызовы оценивания', () => pm.expect(pm.response.json()).to.eql({{attempts:{attempts_count},pipeline_calls:{calls}}}));"])
    def post(name, text=SOLUTION, status=200, tests=None, **kwargs):
        return request_item(name, "POST", "/api/submit", body={"task_id": "{{task_id}}", "text": text}, status=status,
                            schema=ref("AttemptOut") if status == 200 else ref("ValidationProblem") if status == 422 else ref("DetailError"), tests=tests, **kwargs)
    cases = []
    cases.append(("P01 · Оценка и история только своего ученика", "final", [
        post("Отправить решение", tests=["pm.test('Получен полный балл', () => {pm.expect(body.score).to.eql(2); pm.expect(body.is_solved).to.eql(true);});", "pm.collectionVariables.set('attempt_id', body.id);"]),
        request_item("Найти свою попытку в истории", "GET", "/api/tasks/{{task_id}}/attempts?limit=50&offset=0", schema={"type": "array", "items": ref("AttemptOut")}, tests=["pm.test('Своя сохранённая попытка', () => {pm.expect(body).to.have.lengthOf(1); pm.expect(body[0].id).to.eql(pm.collectionVariables.get('attempt_id'));});"]),
        request_item("История другого ученика пуста", "GET", "/api/tasks/{{task_id}}/attempts", auth=bearer("other_token"), schema={"type": "array", "items": ref("AttemptOut")}, tests=["pm.test('Данные изолированы', () => pm.expect(body).to.eql([]));"]), request_item("Недопустимый limit", "GET", "/api/tasks/{{task_id}}/attempts?limit=0", status=422, schema=ref("HTTPValidationError")),
        request_item("Отрицательный offset", "GET", "/api/tasks/{{task_id}}/attempts?offset=-1", status=422, schema=ref("HTTPValidationError")), state(1, 1)]))
    long_body = json.dumps({"task_id": "{{task_id}}", "text": "__LONG__"}).replace('"__LONG__"', '{{long_text_json}}')
    cases.append(("P02 · Валидация и фактическое обрезание текста", "final", [
        post("Пустой текст", "", 422), post("Пробельный текст", "   ", 422),
        request_item("Нет task_id", "POST", "/api/submit", body={"text": SOLUTION}, status=422, schema=ref("ValidationProblem")),
        request_item("Неверный тип текста", "POST", "/api/submit", body={"task_id": "{{task_id}}", "text": 123}, status=422, schema=ref("ValidationProblem")), state(0, 0),
        request_item("Слишком длинный текст: текущий API обрезает", "POST", "/api/submit", body=long_body, schema=ref("AttemptOut"), pre=["pm.variables.set('long_text_json', JSON.stringify('x=1. '.repeat(8001)));"], tests=["pm.test('Фактическое ограничение, GAP-01', () => pm.expect(body.solution_text).to.eql('x=1. '.repeat(8001).slice(0,40000).trim()));"]), state(1, 1)]))
    cases.append(("P03 · Отсутствие авторизации", "final", [post("Без токена", status=401, auth=NOAUTH), post("Повреждённый токен", status=401, auth={"type": "bearer", "bearer": [{"key": "token", "value": "invalid-demo-token", "type": "string"}]}), state(0, 0)]))
    cases.append(("P04 · Неизвестная задача", "final", [request_item("Задачи нет", "POST", "/api/submit", body={"task_id": "missing-demo-task", "text": SOLUTION}, status=404, schema=ref("DetailError")), state(0, 0)]))
    cases.append(("P05 · Превышение частоты", "rate_limit", [post("После 20 отправок за минуту", status=429), state(0, 0)]))
    cases.append(("P06 · Только ответ: расхождение полей", "final", [post("Передать только ответ", "Ответ: 1", tests=["pm.test('Зафиксирован GAP-06', () => {pm.expect(body.feedback.score).to.eql(0); pm.expect(body.score).to.eql(null); pm.expect(body.max_score).to.eql(null); pm.expect(body.is_solved).to.eql(false);});"]), state(1, 0)]))
    cases.append(("P07 · Признак ручной проверки", "provisional", [post("Один оценщик недоступен", tests=["pm.test('Текущий признак куратора', () => {pm.expect(body.score).to.eql(1); pm.expect(body.needs_curator).to.eql(true); pm.expect(body.is_solved).to.eql(false); pm.expect(body).not.to.have.property('review');});"]), state(1, 1)]))
    cases.append(("P08 · Технические отказы", "grading_failure", [post("Отказ оценивания возвращает 200 и ноль", tests=["pm.test('Зафиксирован GAP-03', () => {pm.expect(body.score).to.eql(0); pm.expect(body.needs_curator).to.eql(true);});"]), state(1, 1), reset("save_failure"),
        request_item("Подтверждённый отказ сохранения", "POST", "/api/submit", body={"task_id": "{{task_id}}", "text": SOLUTION}, status=500, tests=["pm.test('Не возвращён успешный результат', () => pm.expect(pm.response.text()).to.eql('Internal Server Error'));"]), state(0, 1)]))
    for title, mode, items in cases:
        col["item"].append({"name": title, "item": [reset(mode), *items]})
    return col


def build_target_collection(spec):
    col = collection_base("PredelAI · UC-01 · целевой API 2.0", "Проектные запросы и ожидания; сервер v2 пока не реализован. Заполнить base_url и токены после появления реализации. Для P07/P08 требуется управляемая подстановка отказов на тестовом сервере; тело запроса не выбирает поведение модели. Служебных /_demo запросов здесь нет. См. протокол и сохранённые примеры в OpenAPI.", definitions(spec), "")
    col["event"] = [{"listen": "prerequest", "script": {"type": "text/javascript", "exec": ["if (!pm.variables.get('base_url') || !pm.variables.get('token')) { throw new Error('Задайте адрес реализации v2 и токен тестового ученика'); }"]}}]
    def post(name, body=None, status=200, auth=None, tests=None, pre=None):
        item = request_item(name, "POST", "/api/v2/submit", body=body or {"task_id": "{{task_id}}", "text": SOLUTION}, status=status,
            schema=ref("AttemptV2") if status == 200 else spec["paths"]["/api/v2/submit"]["post"]["responses"][str(status)]["content"]["application/json"]["schema"], tests=tests, auth=auth, pre=pre)
        if status == 200:
            item["event"][-1]["script"]["exec"] += ["pm.test('Балл и окончательность согласованы', () => {if(body.score !== null){pm.expect(body.score).to.be.at.most(body.max_score);} if(body.result_status==='final'){pm.expect(body.is_solved).to.eql(body.score===body.max_score);} else {pm.expect(body.is_solved).to.eql(false); pm.expect(body.decision.reason_codes.length).to.be.above(0); pm.expect(body.review.id).to.be.a('string').and.not.empty;}});"]
        return item
    col["item"] = [
        {"name": "P01 · Окончательный результат и история", "item": [post("Получить окончательную оценку", tests=["pm.test('Окончательная оценка', () => pm.expect(body.result_status).to.eql('final'));", "pm.collectionVariables.set('attempt_id', body.id);"]), request_item("Найти попытку в своей истории", "GET", "/api/v2/tasks/{{task_id}}/attempts?limit=50&offset=0", schema={"type": "array", "items": ref("AttemptV2")}, tests=["pm.test('Попытка есть в истории', () => pm.expect(body.some(x=>x.id===pm.collectionVariables.get('attempt_id'))).to.eql(true));"]), request_item("Проверить изоляцию другого ученика", "GET", "/api/v2/tasks/{{task_id}}/attempts", auth=bearer("other_token"), schema={"type": "array", "items": ref("AttemptV2")}, tests=["pm.test('Чужая попытка не раскрыта', () => pm.expect(body.some(x=>x.id===pm.collectionVariables.get('attempt_id'))).to.eql(false));"])]},
        {"name": "P02 · Недопустимый текст", "item": [post("Пробельная строка", body={"task_id": "{{task_id}}", "text": "   "}, status=422), post("Превышение 40 000 символов", body='{"task_id":"{{task_id}}","text":{{long_text_json}}}', status=422, pre=["pm.variables.set('long_text_json', JSON.stringify('x=1. '.repeat(8001)));"])]},
        {"name": "P03 · Без авторизации", "item": [post("Токен не передан", status=401, auth=NOAUTH)]},
        {"name": "P04 · Неизвестная задача", "item": [post("Неизвестный ID", body={"task_id": "missing-demo-task", "text": SOLUTION}, status=404)]},
        {"name": "P05 · Ограничение частоты", "item": [post("При исчерпанном лимите", status=429, tests=["pm.test('Время повторной отправки задано', () => {pm.expect(pm.response.headers.has('Retry-After')).to.eql(true); pm.expect(Number(pm.response.headers.get('Retry-After'))).to.be.above(0);});"])]},
        {"name": "P06 · Только ответ", "item": [post("Предметный ноль", body={"task_id": "{{task_id}}", "text": "Ответ: 1"}, tests=["pm.test('Окончательный предметный отказ', () => {pm.expect(body.score).to.eql(0); pm.expect(body.result_status).to.eql('final'); pm.expect(body.decision.source).to.eql('input_rule');});"])]},
        {"name": "P07 · Один оценщик недоступен", "item": [post("Предварительный результат", tests=["pm.test('Есть сохранённая задача куратора', () => {pm.expect(body.result_status).to.eql('provisional'); pm.expect(body.review.status).to.eql('pending');});"])]},
        {"name": "P08 · Технические отказы", "item": [post("Оценка не получена", status=503, tests=["pm.test('Нет технического балла', () => {pm.expect(body.result).to.eql(null); pm.expect(body.error.code).to.eql('GRADING_UNAVAILABLE');});"]), post("Подтверждённый отказ сохранения", status=500, tests=["pm.test('Сохранение не подтверждено', () => pm.expect(body.error.code).to.eql('PERSISTENCE_FAILURE'));"])]},
    ]
    return col


def main():
    current, target = build_current(), build_target()
    for name, spec in [("current", current), ("target-v2", target)]:
        (CASE_ROOT / "contracts" / f"openapi-{name}.yaml").write_text(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False, width=110))
    save_json(CASE_ROOT / "postman/uc01-current.postman_collection.json", build_current_collection(current))
    save_json(CASE_ROOT / "postman/uc01-target-v2.postman_collection.json", build_target_collection(target))
    print("Созданы две OpenAPI-спецификации и две коллекции Postman.")


if __name__ == "__main__":
    main()
