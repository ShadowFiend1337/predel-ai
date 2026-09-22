"""Подготовить CSV исходной выборки для SQL, сохранив рабочие данные вне кейса.

python tools/prepare_sql_dataset.py source.csv --output-dir /tmp/predel-real-sql
Исходный файл не изменяется. Пропуски и ошибки типов не превращаются в ноль.
"""
import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

CASE_ROOT = Path(__file__).resolve().parents[1]
IDS = ["answer_id", "ai_check_id", "task_id", "question_id", "stud_id"]
SCORES = ["max_points", "ai_points", "curator_points"]
DATES = ["sent_to_review_at", "curator_reviewed_at"]
REQUIRED = IDS + SCORES + DATES + ["task_number", "ai_comment", "curator_comment"]


def prepare(source, output):
    output = output.resolve()
    if output.is_relative_to(CASE_ROOT.parent):
        raise ValueError("Рабочие данные должны храниться вне папки проекта")
    source_bytes = source.read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    rows, issues = [], []

    def issue(row, field, kind):
        issues.append({"source_row": row, "field": field, "kind": kind})

    with source.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(REQUIRED) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Нет обязательных полей: {sorted(missing)}")
        for number, original in enumerate(reader, 2):
            if None in original or any(value is None for value in original.values()):
                raise ValueError(f"Нарушена структура CSV в строке {number}")
            record = {"source_row": number}
            for name in IDS:
                record[name] = original[name].strip() or None
                if record[name] is None:
                    issue(number, name, "missing")
            for name in SCORES + ["task_number"]:
                raw = original[name].strip()
                if not raw:
                    record[name] = None
                    issue(number, name, "missing")
                    continue
                try:
                    value = Decimal(raw.replace(",", "."))
                    if not value.is_finite() or (name == "task_number" and value != value.to_integral_value()):
                        raise InvalidOperation
                    # decimal сохраняется строкой: PostgreSQL разбирает его как numeric без потери точности.
                    record[name] = int(value) if name == "task_number" else str(value)
                except InvalidOperation:
                    record[name] = None
                    issue(number, name, "invalid_number")
            for name in DATES:
                raw = original[name]
                record[name + "_raw"] = raw or None
                stripped = raw.strip()
                if not stripped:
                    record[name] = None
                    issue(number, name, "missing")
                    continue
                try:
                    # Формат источника без часового пояса; не добавляем выдуманный UTC/MSK.
                    value = datetime.strptime(stripped, "%Y-%m-%d %H:%M:%S")
                    record[name] = value.strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    record[name] = None
                    issue(number, name, "invalid_timestamp")
            for name in ["ai_comment", "curator_comment"]:
                record[name] = original[name] or None
            rows.append(record)
        headers = reader.fieldnames

    duplicates = {name: sum(n > 1 for n in Counter(row[name] for row in rows if row[name] is not None).values()) for name in ["answer_id", "ai_check_id"]}
    if any(duplicates.values()):
        raise ValueError(f"Повторные ID: {duplicates}. Требуется согласовать единицу анализа до расчёта.")
    if any(row[name] is None for row in rows for name in ["answer_id", "task_id", "task_number"]):
        raise ValueError("Нет ключевых ID или номера задания; требуется уточнить записи до расчёта")

    output.mkdir(parents=True, exist_ok=True)
    prepared = json.dumps(rows, ensure_ascii=False).encode("utf-8")
    (output / "prepared.json").write_bytes(prepared)
    (output / "import-issues.json").write_text(json.dumps(issues, ensure_ascii=False, indent=2) + "\n")
    counts = Counter((item["field"], item["kind"]) for item in issues)
    manifest = {
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": source_sha,
        "source_bytes": len(source_bytes),
        "source_headers": headers,
        "source_rows": len(rows),
        "prepared_rows": len(rows),
        "rows_dropped": 0,
        "prepared_sha256": hashlib.sha256(prepared).hexdigest(),
        "duplicate_id_groups": duplicates,
        "import_issues": [{"field": field, "kind": kind, "count": count} for (field, kind), count in sorted(counts.items())],
        "timezone": "not_confirmed; source timestamps are naive",
        "ai_system": "Стобалльный репетитор",
        "model_version": "not_provided",
        "reference_score": "curator_points, confirmed by case owner",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"rows": len(rows), "issues": manifest["import_issues"], "source_sha256": source_sha}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.source, args.output_dir)
