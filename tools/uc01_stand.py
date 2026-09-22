"""Изолированный стенд действующих маршрутов UC-01: без БД и вызовов ИИ.

Запуск из любого каталога: python tools/uc01_stand.py --serve
Нужны зависимости backend проекта. Служебные /_demo/... не входят в API Predel.
"""
from __future__ import annotations

import argparse
import copy
import secrets
import sys
import time
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

CASE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = CASE_ROOT.parent
sys.path.insert(0, str(WORKSPACE / "predel/backend"))

from fastapi import APIRouter, FastAPI, Request
from pydantic import BaseModel
from typing import Literal

from app.api.routers import attempts, submit
from app.api.schemas.attempt import Feedback
from app.core import deps, rate_limit, security
from app.domain.tasks.entities import Task

TASK_ID = "demo-ege13-001"
SOLUTION = "а) 2cos(x) - 1 = 0, откуда cos(x) = 1/2. Поэтому x = ±π/3 + 2πn, n ∈ Z. б) На отрезке [0; 2π] получаем π/3 и 5π/3. Ответ: а) ±π/3 + 2πn, n ∈ Z; б) π/3, 5π/3."
MODES = Literal["final", "provisional", "grading_failure", "rate_limit", "save_failure"]


class ResetIn(BaseModel):
    scenario: MODES = "final"


def create_stand() -> FastAPI:
    app = FastAPI(title="Изолированный стенд UC-01", version="1.0")
    routes = [r for r in submit.router.routes if r.path == "/submit"]
    routes += [r for r in attempts.router.routes if r.path == "/tasks/{task_id}/attempts"]
    app.include_router(APIRouter(routes=routes), prefix="/api")
    state = {"mode": "final", "rows": [], "pipeline_calls": 0}
    secret = secrets.token_urlsafe(40)
    demo_settings = SimpleNamespace(JWT_SECRET=secret, JWT_ALG="HS256")
    task = Task(id=TASK_ID, theme_id="ege13", name="Задание 13", difficulty="medium",
                statement_md="а) Решите уравнение 2cos(x) − 1 = 0. б) Найдите корни на [0; 2π].",
                reference_solution_md=SOLUTION, theme_title="Задание 13", source="ege13")

    class Tasks:
        async def get(self, task_id):
            return task if task_id == TASK_ID else None

    class Users:
        async def get(self, user_id):
            return None

    class Attempts:
        async def save(self, payload):
            if state["mode"] == "save_failure":
                raise RuntimeError("Демонстрационный отказ сохранения")
            row = copy.deepcopy(payload)
            row["text"] = row.pop("solution_text", "")
            row["max_score"] = row["feedback"].get("max_score")
            state["rows"].append(row)
            return row["id"]

        async def list(self, *, task_id, user_id, limit, offset):
            rows = [r for r in reversed(state["rows"]) if r["task_id"] == task_id and r["user_id"] == user_id]
            return copy.deepcopy(rows[offset:offset + limit])

    uow = SimpleNamespace(tasks=Tasks(), attempts=Attempts(), users=Users())

    async def demo_uow():
        yield uow

    async def fixture_pipeline(**kwargs):
        state["pipeline_calls"] += 1
        if state["mode"] == "grading_failure":
            raise RuntimeError("Демонстрационный отказ оценивания")
        provisional = state["mode"] == "provisional"
        score = 1.0 if provisional else 2.0
        reason = "Оценщик B недоступен" if provisional else ""
        feedback = Feedback(checked=True, general_comment=reason or "Решение соответствует критериям.",
                            score=score, max_score=2, needs_curator=provisional,
                            review_required=provisional, review_reason=reason,
                            final_decision="MANUAL_REVIEW_REQUIRED" if provisional else "AUTO_ACCEPT")
        return {"score": score, "max_score": 2.0, "is_solved": not provisional,
                "feedback": feedback, "grading_result": SimpleNamespace(final_score=score),
                "path": "demo_fixture", "step_parser_artifact": {"status": "skipped", "reason": "Изолированный стенд"}}

    submit._run_standalone_ege_pipeline = fixture_pipeline
    submit.get_settings = lambda: SimpleNamespace(CHECK_SOLUTION_TIMEOUT_SEC=180, MAX_EXTRACTED_TEXT_CHARS=40000)
    app.dependency_overrides[deps.get_uow] = demo_uow
    app.dependency_overrides[deps.get_llm] = lambda: None
    app.dependency_overrides[deps.get_storage] = lambda: None
    app.dependency_overrides[security._get_settings] = lambda: demo_settings
    app.state.demo = state

    @app.post("/_demo/session", include_in_schema=False)
    async def session():
        def token(user):
            return security.create_token({"sub": user, "login": user}, secret, "HS256", timedelta(hours=2))
        return {"mode": "current_source_fixture", "token": token("demo-a"),
                "other_token": token("demo-b"), "task_id": TASK_ID}

    @app.post("/_demo/reset", include_in_schema=False)
    async def reset(payload: ResetIn, request: Request):
        state.update(mode=payload.scenario, rows=[], pipeline_calls=0)
        rate_limit._WINDOWS.clear()
        if payload.scenario == "rate_limit":
            key = f"submit:demo-a:{request.client.host}"
            rate_limit._WINDOWS[key].extend([time.time()] * 20)
        return {"scenario": payload.scenario}

    @app.get("/_demo/state", include_in_schema=False)
    async def inspect_state():
        return {"attempts": len(state["rows"]), "pipeline_calls": state["pipeline_calls"]}

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true", help="Запустить HTTP-стенд на 127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.serve:
        import uvicorn
        uvicorn.run(create_stand(), host="127.0.0.1", port=args.port, log_level="warning")
    else:
        parser.print_help()
