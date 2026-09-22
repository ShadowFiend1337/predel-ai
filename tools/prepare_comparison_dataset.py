"""Подготовка второй CSV: только числовые оценки и служебные ключи вне кейса."""
import argparse
import csv
import hashlib
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    case = Path(__file__).resolve().parents[1]
    output = args.output_dir.resolve()
    if output == case.parent or case.parent in output.parents:
        parser.error("Рабочие данные нужно сохранять вне общего каталога проекта")
    with args.csv_path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source)
        headers = next(reader)
        required = ["task_id", "original_row_id", "their_ai_score", "PredelAI_score",
                    "curator_score", "true_score", "task_text", "solution_photo"]
        for name in required:
            if headers.count(name) != 1:
                raise ValueError(f"Не найден единственный столбец {name}")
        positions = {name: headers.index(name) for name in required}
        rows, conditions, photos = [], set(), []

        def score(raw, line, name):
            raw = raw.strip()
            if raw in ("", "-"):
                return None
            try:
                value = Decimal(raw.replace(",", "."))
            except InvalidOperation:
                raise ValueError(f"Строка {line}: некорректный балл в {name}") from None
            if not value.is_finite() or value < 0:
                raise ValueError(f"Строка {line}: недопустимый балл в {name}")
            return str(value)

        for line, cells in enumerate(reader, start=2):
            if not any(cell.strip() for cell in cells):
                continue
            if len(cells) <= max(positions.values()):
                raise ValueError(f"Строка {line}: не хватает столбцов")
            get = lambda name: cells[positions[name]].strip()
            task_number = int(get("task_id"))
            if task_number <= 0:
                raise ValueError(f"Строка {line}: неверный номер задания")
            row = {"work_id": line - 1, "task_number": task_number,
                   "original_row_id": get("original_row_id") or None}
            for dest, src in [("predel_score", "PredelAI_score"),
                              ("their_score", "their_ai_score"),
                              ("curator_score", "curator_score"),
                              ("true_score", "true_score")]:
                row[dest] = score(get(src), line, src)
            rows.append(row)
            conditions.add(get("task_text"))
            photos.append(get("solution_photo"))

    ids = Counter(row["original_row_id"] for row in rows if row["original_row_id"])
    present_photos = [photo for photo in photos if photo]
    manifest = {
        "source_url": "https://docs.google.com/spreadsheets/d/1fG-4JZTYh6hDkqvYx55OD-Q1rdC5beDTeAe97ubSD9w/edit?gid=0",
        "sheet": "Лист1",
        "sha256": hashlib.sha256(args.csv_path.read_bytes()).hexdigest(),
        "rows": len(rows), "raw_columns": len(headers),
        "distinct_task_texts": len(conditions),
        "repeated_original_id_groups": sum(n > 1 for n in ids.values()),
        "missing_original_ids": sum(row["original_row_id"] is None for row in rows),
        "repeated_photo_groups": sum(n > 1 for n in Counter(present_photos).values()),
        "missing_photos": len(photos) - len(present_photos),
        "reference": "true_score", "reference_author": "Команда проекта",
        "usage": "Выборка использовалась при разработке",
        "model_versions": None,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "prepared-comparison.json").write_text(
        json.dumps({"source": manifest, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
