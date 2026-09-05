"""Phase 8: the local skill (create/review/edit/activate/archive/invoke) API."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import skill_service
from app.deps import get_db
from app.models_actions import Skill, SkillVersion
from app.routers.actions import proposal_to_read
from app.schemas_actions import (
    SkillCreateRequest,
    SkillEditRequest,
    SkillInvokeRequest,
    SkillInvokeResult,
    SkillRead,
    SkillVersionRead,
    SkillWithHistory,
)

router = APIRouter(tags=["skills"])


def _skill_to_read(skill: Skill) -> SkillRead:
    return SkillRead(
        id=skill.id,
        slug=skill.slug,
        name=skill.name,
        description=skill.description,
        domain_id=skill.domain_id,
        invocation_phrases=json.loads(skill.invocation_phrases_json),
        status=skill.status,
        created_by=skill.created_by,
        current_version_id=skill.current_version_id,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
    )


def _version_to_read(version: SkillVersion) -> SkillVersionRead:
    return SkillVersionRead(
        id=version.id,
        skill_id=version.skill_id,
        version_number=version.version_number,
        name=version.name,
        description=version.description,
        workflow_steps=json.loads(version.workflow_steps_json),
        change_reason=version.change_reason,
        created_at=version.created_at,
    )


@router.post("/api/skills", response_model=SkillRead, status_code=201)
def create_skill(payload: SkillCreateRequest, db: Session = Depends(get_db)) -> SkillRead:
    try:
        skill = skill_service.create_skill(
            db,
            slug=payload.slug,
            name=payload.name,
            description=payload.description,
            domain_id=payload.domain_id,
            invocation_phrases=payload.invocation_phrases,
            workflow_steps=payload.workflow_steps,
            created_by="user",
        )
    except skill_service.SkillError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _skill_to_read(skill)


@router.get("/api/skills", response_model=list[SkillRead])
def list_skills(
    status: str | None = Query(default=None),
    domain_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[SkillRead]:
    skills = skill_service.list_skills(db, status=status, domain_id=domain_id)
    return [_skill_to_read(s) for s in skills]


@router.get("/api/skills/{skill_id}", response_model=SkillWithHistory)
def get_skill(skill_id: str, db: Session = Depends(get_db)) -> SkillWithHistory:
    try:
        skill = skill_service.get_skill_or_404(db, skill_id)
    except skill_service.SkillNotFoundError:
        raise HTTPException(status_code=404, detail="Skill not found")
    return SkillWithHistory(
        skill=_skill_to_read(skill), versions=[_version_to_read(v) for v in skill.versions]
    )


@router.post("/api/skills/{skill_id}/edit", response_model=SkillRead)
def edit_skill(skill_id: str, payload: SkillEditRequest, db: Session = Depends(get_db)) -> SkillRead:
    try:
        skill = skill_service.edit_skill(
            db,
            skill_id,
            name=payload.name,
            description=payload.description,
            workflow_steps=payload.workflow_steps,
            change_reason=payload.change_reason,
        )
    except skill_service.SkillNotFoundError:
        raise HTTPException(status_code=404, detail="Skill not found")
    except skill_service.SkillError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _skill_to_read(skill)


@router.post("/api/skills/{skill_id}/activate", response_model=SkillRead)
def activate_skill(skill_id: str, db: Session = Depends(get_db)) -> SkillRead:
    try:
        skill = skill_service.activate_skill(db, skill_id)
    except skill_service.SkillNotFoundError:
        raise HTTPException(status_code=404, detail="Skill not found")
    except skill_service.SkillError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _skill_to_read(skill)


@router.post("/api/skills/{skill_id}/archive", response_model=SkillRead)
def archive_skill(skill_id: str, db: Session = Depends(get_db)) -> SkillRead:
    try:
        skill = skill_service.archive_skill(db, skill_id)
    except skill_service.SkillNotFoundError:
        raise HTTPException(status_code=404, detail="Skill not found")
    return _skill_to_read(skill)


@router.post("/api/skills/{skill_id}/invoke", response_model=SkillInvokeResult)
def invoke_skill(skill_id: str, payload: SkillInvokeRequest, db: Session = Depends(get_db)) -> SkillInvokeResult:
    try:
        proposals = skill_service.invoke_skill(
            db, skill_id, step_arguments=payload.step_arguments, reason=payload.reason
        )
    except skill_service.SkillNotFoundError:
        raise HTTPException(status_code=404, detail="Skill not found")
    except skill_service.SkillError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SkillInvokeResult(proposals=[proposal_to_read(p) for p in proposals])
