"""Pydantic request/response models for the Phase 8 action/skill API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ActionAuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action_proposal_id: str
    event_type: str
    detail: str | None
    created_at: datetime


class ActionProposalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    capability_id: str
    domain_id: str | None
    permission_level: str
    arguments: dict[str, Any]
    reason: str
    expected_effect: str
    payload_digest: str
    status: str
    source: str
    confirmation_token: str | None
    confirmation_expires_at: datetime | None
    result: dict[str, Any] | None
    error_summary: str | None
    created_at: datetime
    updated_at: datetime


class ActionProposalWithHistory(BaseModel):
    proposal: ActionProposalRead
    audit_events: list[ActionAuditEventRead]


class ActionProposeRequest(BaseModel):
    capability_id: str
    domain_id: str | None = None
    arguments: dict[str, Any]
    reason: str = Field(min_length=1, max_length=1000)


class ActionApproveRequest(BaseModel):
    payload_digest: str


class ActionExecuteRequest(BaseModel):
    confirmation_token: str


class ActionDenyRequest(BaseModel):
    reason: str | None = None


class SkillVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    skill_id: str
    version_number: int
    name: str
    description: str
    workflow_steps: list[dict[str, Any]]
    change_reason: str | None
    created_at: datetime


class SkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    name: str
    description: str
    domain_id: str | None
    invocation_phrases: list[str]
    status: str
    created_by: str
    current_version_id: str | None
    created_at: datetime
    updated_at: datetime


class SkillWithHistory(BaseModel):
    skill: SkillRead
    versions: list[SkillVersionRead]


class SkillCreateRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    domain_id: str | None = None
    invocation_phrases: list[str] = Field(default_factory=list)
    workflow_steps: list[dict[str, Any]]


class SkillEditRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    workflow_steps: list[dict[str, Any]]
    change_reason: str | None = None


class SkillInvokeRequest(BaseModel):
    step_arguments: list[dict[str, Any]]
    reason: str | None = None


class SkillInvokeResult(BaseModel):
    proposals: list[ActionProposalRead]
