"""Validated payload models for each structured-record type.

A discriminated-union-style dispatch keyed on `record_type` — every payload
must validate against exactly one of these models before being stored.
Arbitrary unbounded JSON is never accepted.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.models_memory import STRUCTURED_RECORD_TYPES


class BodyWeightPayload(BaseModel):
    record_type: Literal["body_weight"] = "body_weight"
    kilograms: float = Field(gt=0, lt=500)
    original_text: str | None = Field(default=None, max_length=100)


class BodySymptomPayload(BaseModel):
    record_type: Literal["body_symptom"] = "body_symptom"
    body_area: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1000)
    severity: int | None = Field(default=None, ge=1, le=10)
    trigger: str | None = Field(default=None, max_length=300)


class MindCheckinPayload(BaseModel):
    record_type: Literal["mind_checkin"] = "mind_checkin"
    mood: str = Field(min_length=1, max_length=50)
    note: str | None = Field(default=None, max_length=1000)


class PeopleInteractionPayload(BaseModel):
    record_type: Literal["people_interaction"] = "people_interaction"
    person: str = Field(min_length=1, max_length=100)
    note: str = Field(min_length=1, max_length=1000)


class PathDeadlinePayload(BaseModel):
    record_type: Literal["path_deadline"] = "path_deadline"
    title: str = Field(min_length=1, max_length=200)
    due_date: str | None = Field(default=None, max_length=32)
    note: str | None = Field(default=None, max_length=1000)


class BuildCheckpointPayload(BaseModel):
    record_type: Literal["build_checkpoint"] = "build_checkpoint"
    project: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=1000)
    decision: str | None = Field(default=None, max_length=500)


class LifeTaskPayload(BaseModel):
    record_type: Literal["life_task"] = "life_task"
    title: str = Field(min_length=1, max_length=200)
    due_date: str | None = Field(default=None, max_length=32)
    note: str | None = Field(default=None, max_length=1000)


_PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "body_weight": BodyWeightPayload,
    "body_symptom": BodySymptomPayload,
    "mind_checkin": MindCheckinPayload,
    "people_interaction": PeopleInteractionPayload,
    "path_deadline": PathDeadlinePayload,
    "build_checkpoint": BuildCheckpointPayload,
    "life_task": LifeTaskPayload,
}

# Which domain slug each record type belongs to — enforced at creation time.
RECORD_TYPE_DOMAIN_SLUG: dict[str, str] = {
    "body_weight": "body",
    "body_symptom": "body",
    "mind_checkin": "mind",
    "people_interaction": "people",
    "path_deadline": "path",
    "build_checkpoint": "build",
    "life_task": "life",
}

assert set(_PAYLOAD_MODELS) == set(STRUCTURED_RECORD_TYPES)


class StructuredRecordValidationError(Exception):
    pass


def validate_payload(record_type: str, payload: dict) -> BaseModel:
    model_cls = _PAYLOAD_MODELS.get(record_type)
    if model_cls is None:
        raise StructuredRecordValidationError(f"Unknown record_type: {record_type!r}")
    try:
        return model_cls.model_validate({**payload, "record_type": record_type})
    except Exception as exc:  # pydantic.ValidationError, kept generic for the caller
        raise StructuredRecordValidationError(str(exc)) from exc
