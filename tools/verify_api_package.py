"""Проверить контракты, примеры и скрипты Postman; сохранить обезличенный протокол.

python tools/verify_api_package.py --newman-report /tmp/predel-newman-report.json
Без --newman-report проверяются только файлы, HTTP-проверки не заявляются.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate_spec
from pydantic import ValidationError

from build_api_package import (
    CASE_ROOT, AttemptOut, AttemptV2, ErrorV2, SubmitTextV2,
    build_current, build_target, build_current_collection, build_target_collection,
    current_examples, target_examples, save_json,
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_examples(spec):
    count = 0

    def walk(value):
        nonlocal count
        if isinstance(value, dict):
            if "schema" in value and isinstance(value["schema"], dict):
                schema = {**value["schema"], "components": spec["components"]}
                validator = Draft202012Validator(schema, format_checker=FormatChecker())
                examples = [e["value"] for e in value.get("examples", {}).values() if "value" in e]
                if "example" in value:
                    examples.append(value["example"])
                for example in examples:
                    validator.validate(example)
                    count += 1
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(spec)
    return count


def check_invariants():
    positives, negatives = [], []

    def accept(name, model, payload):
        model.model_validate_json(json.dumps(payload))
        positives.append(name)

    def reject(name, model, payload):
        try:
            model.model_validate_json(json.dumps(payload))
        except ValidationError:
            negatives.append(name)
        else:
            raise AssertionError(f"Недопустимый пример принят: {name}")

    for name, example in current_examples().items():
        accept("Текущий ответ: " + name, AttemptOut, example)
    for name, example in target_examples().items():
        accept("Целевой ответ: " + name, AttemptV2, example)
    accept("Ровно 40 000 символов Unicode", SubmitTextV2, {"task_id": "demo", "text": "🧮" * 40000})
    for name, data in [
        ("40 001 символ", {"task_id": "demo", "text": "🧮" * 40001}),
        ("Пробелы и переносы строк", {"task_id": "demo", "text": " \n\t"}),
        ("Пустой текст", {"task_id": "demo", "text": ""}),
        ("Нет текста", {"task_id": "demo"}),
        ("Число вместо текста", {"task_id": "demo", "text": 1}),
        ("Пустой идентификатор", {"task_id": " ", "text": "x=1"}),
        ("Неизвестное поле запроса", {"task_id": "demo", "text": "x=1", "user_id": "other"}),
    ]:
        reject(name, SubmitTextV2, data)
    final = target_examples()["окончательная"]
    provisional = target_examples()["предварительная"]
    mutations = [
        ("Балл выше максимума", final, {"score": 3}),
        ("Отрицательный балл", final, {"score": -1}),
        ("Логическое значение вместо балла", final, {"score": True}),
        ("Нулевой максимум", final, {"max_score": 0}),
        ("Нет окончательного балла", final, {"score": None}),
        ("Неверный признак полного решения", final, {"is_solved": False}),
        ("Неизвестное поле ответа", final, {"extra": 1}),
        ("Нет часового пояса", final, {"created_at": "2026-09-15T12:00:00"}),
        ("Окончательная оценка без источника", final, {"decision": {"source": "none", "reason_codes": []}}),
        ("Решение куратора без задачи", final, {"decision": {"source": "curator", "reason_codes": []}}),
        ("Предметный отказ с ненулевым баллом", final, {"decision": {"source": "input_rule", "reason_codes": []}}),
        ("Предварительная оценка без задачи", provisional, {"review": None}),
        ("Предварительная оценка без причины", provisional, {"decision": {"source": "grader_a", "reason_codes": []}}),
        ("Предварительная оценка без источника", provisional, {"decision": {"source": "none", "reason_codes": ["ERROR"]}}),
        ("Предварительная оценка признана полной", provisional, {"is_solved": True}),
        ("Завершённая задача при предварительной оценке", provisional, {"review": {"id": "r", "status": "completed"}}),
    ]
    for name, original, patch in mutations:
        reject(name, AttemptV2, {**copy.deepcopy(original), **patch})
    error = {"schema_version": "2.0", "request_id": "request-demo", "result": None,
             "error": {"code": "GRADING_UNAVAILABLE", "message": "Оценка недоступна", "retryable": True}}
    accept("Техническая ошибка без балла", ErrorV2, error)
    reject("Оценка внутри технической ошибки", ErrorV2, {**error, "result": {"score": 0}})
    reject("Лишний балл в технической ошибке", ErrorV2, {**error, "score": 0})
    return {"valid_examples_accepted": positives, "invalid_examples_rejected": negatives}


def check_scripts(collection):
    scripts = []

    def walk(item):
        scripts.extend("\n".join(event["script"]["exec"]) for event in item.get("event", []))
        for child in item.get("item", []):
            walk(child)

    walk(collection)
    # Только синтаксический разбор: запросы не выполняются, pm не имитируется.
    subprocess.run(["node", "-e", "const fs=require('fs'),vm=require('vm'); for(const s of JSON.parse(fs.readFileSync(0,'utf8'))) new vm.Script(s);"],
                   input=json.dumps(scripts), text=True, check=True, capture_output=True)
    return len(scripts)


def sanitized_run(path, collection):
    raw = json.loads(path.read_text())
    run = raw["run"]
    if run.get("failures") or any(s.get("failed", 0) or s.get("pending", 0) for s in run["stats"].values()):
        raise AssertionError("Newman содержит ошибки или незавершённые проверки; успешный протокол не сформирован")
    expected = [("Подготовка", collection["item"][0])]
    for group in collection["item"][1:]:
        expected.extend((group["name"], item) for item in group["item"])
    executions = run["executions"]
    assert len(executions) == len(expected), "Не все запросы коллекции выполнены"
    rows = []
    for (group, original), execution in zip(expected, executions):
        assert execution["item"]["name"] == original["name"], "Отчёт другой версии коллекции"
        expected_tests = next(e["script"]["exec"] for e in original["event"] if e["listen"] == "test")
        actual_tests = next(e["script"]["exec"] for e in execution["item"]["event"] if e["listen"] == "test")
        assert actual_tests == expected_tests, "Отчёт содержит устаревшие проверки"
        assertions = execution.get("assertions", [])
        assert assertions and not any(a.get("error") or a.get("skipped") for a in assertions)
        row = {"scenario": group, "request": original["name"], "method": original["request"]["method"],
               "path_template": original["request"]["url"].replace("{{base_url}}", ""),
               "http_status": execution["response"]["code"],
               "assertions_passed": [a["assertion"] for a in assertions]}
        # Отчёт Newman содержит учебные JWT. Не копируем заголовки, переменные, полные тела и окружение.
        if "/_demo/session" not in row["path_template"]:
            try:
                body = json.loads(bytes(execution["response"]["stream"]["data"]))
            except (KeyError, ValueError):
                body = None
            if isinstance(body, dict):
                allowed = ["score", "max_score", "is_solved", "needs_curator", "attempts", "pipeline_calls"]
                row["observed"] = {k: body[k] for k in allowed if k in body}
                if "solution_text" in body:
                    row["observed"]["solution_text_characters"] = len(body["solution_text"])
                if "feedback" in body:
                    row["observed"]["feedback_score"] = body["feedback"].get("score")
            elif isinstance(body, list):
                row["observed"] = {"items": len(body)}
        rows.append(row)
    return {"status": "passed_on_isolated_current_routes", "completed_at": datetime.fromtimestamp(run["timings"]["completed"] / 1000, timezone.utc).isoformat(),
            "requests": len(rows), "assertions": run["stats"]["assertions"]["total"], "failures": 0,
            "collection_sha256": digest(CASE_ROOT / "postman/uc01-current.postman_collection.json"),
            "scope": "Реальные HTTP-обработчики, JWT и ограничитель; синтетическое оценивание и хранилище в памяти. Не проверка реальных моделей, БД, интерфейса и целевого API.",
            "executions": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--newman-report", type=Path)
    args = parser.parse_args()
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "openapi": [], "postman": [],
              "target_runtime": {"status": "not_implemented_not_executed"},
              "dependencies": {name: importlib.metadata.version(name) for name in ["openapi-spec-validator", "jsonschema", "pydantic", "fastapi", "PyYAML"]}}
    current_collection = None
    for name, build, build_collection in [("current", build_current, build_current_collection), ("target-v2", build_target, build_target_collection)]:
        path = CASE_ROOT / "contracts" / f"openapi-{name}.yaml"
        spec = yaml.safe_load(path.read_text())
        assert spec == build(), f"Устарела спецификация: {name}"
        validate_spec(spec)
        report["openapi"].append({"file": str(path.relative_to(CASE_ROOT)), "sha256": digest(path),
                                   "valid": True, "examples_validated": check_examples(spec)})
        path = CASE_ROOT / "postman" / f"uc01-{name}.postman_collection.json"
        collection = json.loads(path.read_text())
        assert collection == build_collection(spec), f"Устарела коллекция: {name}"
        report["postman"].append({"file": str(path.relative_to(CASE_ROOT)), "sha256": digest(path),
                                  "scripts_parsed": check_scripts(collection), "matches_generator_and_contract_schemas": True})
        if name == "current":
            current_collection = collection
    report["target_and_current_model_checks"] = check_invariants()
    report["current_runtime"] = sanitized_run(args.newman_report, current_collection) if args.newman_report else {"status": "not_executed_in_this_run"}
    source_paths = ["predel/backend/app/api/routers/submit.py", "predel/backend/app/api/routers/attempts.py",
                    "predel/backend/app/api/schemas/attempt.py", "predel/backend/app/core/security.py",
                    "predel/backend/app/core/rate_limit.py", "predel/backend/app/core/deps.py"]
    source_paths += [str(p.relative_to(CASE_ROOT.parent)) for p in sorted((CASE_ROOT / "tools").glob("*.py"))]
    report["sources"] = [{"path": p, "sha256": digest(CASE_ROOT.parent / p)} for p in source_paths]
    destination = CASE_ROOT / "verification" / ("uc01-api-report.json" if args.newman_report else "api-static-report.json")
    save_json(destination, report)
    print(json.dumps({"report": str(destination), "openapi_examples": sum(s["examples_validated"] for s in report["openapi"]),
                      "valid_model_examples": len(report["target_and_current_model_checks"]["valid_examples_accepted"]),
                      "invalid_model_examples": len(report["target_and_current_model_checks"]["invalid_examples_rejected"]),
                      "current_requests": report["current_runtime"].get("requests", 0),
                      "current_assertions": report["current_runtime"].get("assertions", 0)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
