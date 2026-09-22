"""Проверяемые модели целевого контракта UC-01. Не код приложения Predel."""
from typing import Annotated, Literal, Union

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, RootModel, model_validator

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Score = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SubmitTextV2(StrictModel):
    task_id: Text
    text: Annotated[str, Field(min_length=1, max_length=40000, pattern=r"\S")]


class StudentFeedbackV2(StrictModel):
    general_comment: Text
    comments: list[str]


class DecisionV2(StrictModel):
    source: Literal["primary_agreement", "grader_a", "grader_b", "arbiter", "calibration", "input_rule", "curator", "none"]
    reason_codes: list[Text]


class CompletedReviewV2(StrictModel):
    id: Text
    status: Literal["completed"]


class PendingReviewV2(StrictModel):
    id: Text
    status: Literal["pending", "in_progress"]


class AttemptBaseV2(StrictModel):
    schema_version: Literal["2.0"]
    id: Text
    task_id: Text
    solution_text: Annotated[str, Field(min_length=1, max_length=40000, pattern=r"\S")]
    created_at: AwareDatetime
    max_score: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    feedback: StudentFeedbackV2
    decision: DecisionV2


class FinalAttemptV2(AttemptBaseV2):
    result_status: Literal["final"]
    score: Score
    is_solved: bool
    review: CompletedReviewV2 | None

    @model_validator(mode="after")
    def validate_result(self):
        if self.score > self.max_score:
            raise ValueError("Балл превышает максимум задачи")
        if self.is_solved != (self.score == self.max_score):
            raise ValueError("Признак полного решения не соответствует окончательному баллу")
        if (self.review is not None) != (self.decision.source == "curator"):
            raise ValueError("Решение куратора требует завершённой ручной проверки")
        if self.decision.source == "none":
            raise ValueError("У окончательной оценки должен быть источник")
        if self.decision.source == "input_rule" and self.score != 0:
            raise ValueError("Отказ за отсутствие хода решения требует нулевого балла")
        return self


class ProvisionalAttemptV2(AttemptBaseV2):
    result_status: Literal["provisional"]
    score: Score | None
    is_solved: Literal[False]
    review: PendingReviewV2

    @model_validator(mode="after")
    def validate_result(self):
        if self.score is not None and self.score > self.max_score:
            raise ValueError("Балл превышает максимум задачи")
        if not self.decision.reason_codes:
            raise ValueError("Нужна причина предварительности")
        if self.decision.source in {"curator", "input_rule"}:
            raise ValueError("Источник не относится к предварительному оцениванию")
        if self.score is not None and self.decision.source == "none":
            raise ValueError("У числовой оценки должен быть источник")
        return self


class AttemptV2(RootModel[Annotated[Union[FinalAttemptV2, ProvisionalAttemptV2], Field(discriminator="result_status")]]):
    pass


class ErrorDetailV2(StrictModel):
    code: Literal["AUTH_REQUIRED", "TASK_NOT_FOUND", "VALIDATION_ERROR", "RATE_LIMITED", "GRADING_UNAVAILABLE", "PERSISTENCE_FAILURE", "PERSISTENCE_OUTCOME_UNKNOWN", "INTERNAL_ERROR"]
    message: Text
    retryable: bool


class ErrorV2(StrictModel):
    schema_version: Literal["2.0"]
    request_id: Text
    result: None
    error: ErrorDetailV2
