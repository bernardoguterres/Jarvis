"""Phase 12E: Source-Grounded Research Workspace HTTP surface, built on
top of Phase 12D Unified Recall. Evidence search is read-only (delegates
to `app.recall_service.search()`); every other route here only ever
mutates this feature's own local presentation/analysis state — never a
Calendar/Health/memory mutation, never a tool, never Hermes toolset
configuration. `POST .../briefs/draft` is the one route that reaches a
model, and only via a single `provider.send_turn()` call — see
`app.research_service.draft_brief_with_model`.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import recall_service, research_service
from app.config import Settings, get_settings
from app.deps import get_db, get_provider
from app.models_research import (
    ResearchBriefVersion,
    ResearchEvidence,
    ResearchNote,
    ResearchWorkspace,
)
from app.providers.base import AgentProvider
from app.schemas_recall import RecallResultRead, RecallSearchRead
from app.schemas_research import (
    ResearchBriefVersionRead,
    ResearchBriefVersionSummary,
    ResearchCitationRead,
    ResearchEvidenceAdd,
    ResearchEvidenceRead,
    ResearchEvidenceUpdate,
    ResearchModelMetaRead,
    ResearchNoteCreate,
    ResearchNoteRead,
    ResearchNoteUpdate,
    ResearchWorkspaceCreate,
    ResearchWorkspaceRead,
    ResearchWorkspaceUpdate,
)

router = APIRouter(tags=["research"])


def _workspace_to_read(session: Session, workspace: ResearchWorkspace) -> ResearchWorkspaceRead:
    fields = research_service.workspace_summary_fields(session, workspace)
    return ResearchWorkspaceRead(
        id=workspace.id,
        title=workspace.title,
        domain_slug=fields["domain_slug"],
        included_domain_slugs=fields["included_domain_slugs"],
        status=workspace.status,
        evidence_count=fields["evidence_count"],
        note_count=fields["note_count"],
        latest_brief_version=fields["latest_brief_version"],
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
        archived_at=workspace.archived_at,
    )


def _evidence_to_read(session: Session, evidence: ResearchEvidence) -> ResearchEvidenceRead:
    fields = research_service.evidence_read_fields(session, evidence)
    return ResearchEvidenceRead(
        id=evidence.id,
        workspace_id=evidence.workspace_id,
        source_type=evidence.source_type,
        source_id=evidence.source_id,
        domain_slug=evidence.domain_slug,
        title_snapshot=evidence.title_snapshot,
        snippet_snapshot=evidence.snippet_snapshot,
        occurred_at_snapshot=evidence.occurred_at_snapshot,
        classification=evidence.classification,
        note=evidence.note,
        status=evidence.status,
        available=fields["available"],
        unavailable_reason=fields["unavailable_reason"],
        link_target=fields["link_target"],
        added_at=evidence.added_at,
        updated_at=evidence.updated_at,
    )


def _note_to_read(note: ResearchNote) -> ResearchNoteRead:
    return ResearchNoteRead(
        id=note.id,
        workspace_id=note.workspace_id,
        content=note.content,
        linked_evidence_ids=json.loads(note.linked_evidence_ids_json),
        status=note.status,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


def _brief_to_read(session: Session, version: ResearchBriefVersion) -> ResearchBriefVersionRead:
    citations = [ResearchCitationRead(**c) for c in research_service.citation_reads(session, version)]
    model_meta = ResearchModelMetaRead(**json.loads(version.model_meta_json)) if version.model_meta_json else None
    return ResearchBriefVersionRead(
        id=version.id,
        workspace_id=version.workspace_id,
        version_number=version.version_number,
        source=version.source,
        status=version.status,
        title=version.title,
        sections_json=version.sections_json,
        citations=citations,
        validation_issues=json.loads(version.validation_json),
        model_meta=model_meta,
        generated_at=version.generated_at,
        created_at=version.created_at,
    )


def _handle(fn):
    try:
        return fn()
    except research_service.ResearchNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except research_service.ResearchModelError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except research_service.ResearchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --- workspaces ----------------------------------------------------------------


@router.post("/api/research/workspaces", response_model=ResearchWorkspaceRead, status_code=201)
def create_workspace(payload: ResearchWorkspaceCreate, db: Session = Depends(get_db)) -> ResearchWorkspaceRead:
    def _run():
        workspace = research_service.create_workspace(
            db,
            title=payload.title,
            domain_slug=payload.domain_slug,
            included_domain_slugs_arg=payload.included_domain_slugs,
        )
        return _workspace_to_read(db, workspace)

    return _handle(_run)


@router.get("/api/research/workspaces", response_model=list[ResearchWorkspaceRead])
def list_workspaces(status: str | None = Query(default=None), db: Session = Depends(get_db)) -> list[ResearchWorkspaceRead]:
    if status is not None and status not in ("active", "archived"):
        raise HTTPException(status_code=400, detail="status must be 'active' or 'archived'.")
    workspaces = research_service.list_workspaces(db, status=status)
    return [_workspace_to_read(db, w) for w in workspaces]


@router.get("/api/research/workspaces/{workspace_id}", response_model=ResearchWorkspaceRead)
def get_workspace(workspace_id: str, db: Session = Depends(get_db)) -> ResearchWorkspaceRead:
    return _handle(lambda: _workspace_to_read(db, research_service.get_workspace(db, workspace_id)))


@router.put("/api/research/workspaces/{workspace_id}", response_model=ResearchWorkspaceRead)
def update_workspace(
    workspace_id: str, payload: ResearchWorkspaceUpdate, db: Session = Depends(get_db)
) -> ResearchWorkspaceRead:
    fields = payload.model_dump(exclude_unset=True)

    def _run():
        workspace = research_service.update_workspace(
            db,
            workspace_id,
            title=fields.get("title"),
            included_domain_slugs_arg=fields.get("included_domain_slugs"),
        )
        return _workspace_to_read(db, workspace)

    return _handle(_run)


@router.post("/api/research/workspaces/{workspace_id}/archive", response_model=ResearchWorkspaceRead)
def archive_workspace(workspace_id: str, db: Session = Depends(get_db)) -> ResearchWorkspaceRead:
    return _handle(lambda: _workspace_to_read(db, research_service.archive_workspace(db, workspace_id)))


@router.post("/api/research/workspaces/{workspace_id}/reopen", response_model=ResearchWorkspaceRead)
def reopen_workspace(workspace_id: str, db: Session = Depends(get_db)) -> ResearchWorkspaceRead:
    return _handle(lambda: _workspace_to_read(db, research_service.reopen_workspace(db, workspace_id)))


# --- evidence discovery (read-only, delegates to Recall) -----------------------


@router.get("/api/research/workspaces/{workspace_id}/evidence/search", response_model=RecallSearchRead)
def search_evidence_candidates(
    workspace_id: str,
    q: str = Query(default=""),
    source_types: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=recall_service.RECALL_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> RecallSearchRead:
    types = [s.strip() for s in source_types.split(",") if s.strip()] if source_types is not None else None

    def _run():
        result = research_service.search_workspace_evidence(db, workspace_id, q, source_types=types, limit=limit, offset=offset)
        return RecallSearchRead(
            query=result.query,
            results=[
                RecallResultRead(
                    source_type=r.source_type,
                    source_id=r.source_id,
                    domain_slug=r.domain_slug,
                    title=r.title,
                    snippet_html=r.snippet_html,
                    occurred_at=r.occurred_at,
                    link_target=r.link_target,
                    available=r.available,
                    unavailable_reason=r.unavailable_reason,
                )
                for r in result.results
            ],
            total_considered=result.total_considered,
            limit=result.limit,
            offset=result.offset,
            has_more=result.has_more,
            partial_failures=result.partial_failures,
        )

    return _handle(_run)


# --- evidence --------------------------------------------------------------


@router.get("/api/research/workspaces/{workspace_id}/evidence", response_model=list[ResearchEvidenceRead])
def list_evidence(workspace_id: str, db: Session = Depends(get_db)) -> list[ResearchEvidenceRead]:
    def _run():
        research_service.get_workspace(db, workspace_id)
        return [_evidence_to_read(db, e) for e in research_service.list_evidence(db, workspace_id)]

    return _handle(_run)


@router.post("/api/research/workspaces/{workspace_id}/evidence", response_model=ResearchEvidenceRead, status_code=201)
def add_evidence(workspace_id: str, payload: ResearchEvidenceAdd, db: Session = Depends(get_db)) -> ResearchEvidenceRead:
    def _run():
        evidence = research_service.add_evidence(
            db,
            workspace_id,
            source_type=payload.source_type,
            source_id=payload.source_id,
            classification=payload.classification,
            note=payload.note,
        )
        return _evidence_to_read(db, evidence)

    return _handle(_run)


@router.put(
    "/api/research/workspaces/{workspace_id}/evidence/{evidence_id}", response_model=ResearchEvidenceRead
)
def update_evidence(
    workspace_id: str, evidence_id: str, payload: ResearchEvidenceUpdate, db: Session = Depends(get_db)
) -> ResearchEvidenceRead:
    def _run():
        evidence = research_service.update_evidence(
            db, workspace_id, evidence_id, classification=payload.classification, note=payload.note
        )
        return _evidence_to_read(db, evidence)

    return _handle(_run)


@router.post(
    "/api/research/workspaces/{workspace_id}/evidence/{evidence_id}/remove", response_model=ResearchEvidenceRead
)
def remove_evidence(workspace_id: str, evidence_id: str, db: Session = Depends(get_db)) -> ResearchEvidenceRead:
    return _handle(lambda: _evidence_to_read(db, research_service.remove_evidence(db, workspace_id, evidence_id)))


# --- notes -------------------------------------------------------------------


@router.get("/api/research/workspaces/{workspace_id}/notes", response_model=list[ResearchNoteRead])
def list_notes(workspace_id: str, db: Session = Depends(get_db)) -> list[ResearchNoteRead]:
    def _run():
        research_service.get_workspace(db, workspace_id)
        return [_note_to_read(n) for n in research_service.list_notes(db, workspace_id)]

    return _handle(_run)


@router.post("/api/research/workspaces/{workspace_id}/notes", response_model=ResearchNoteRead, status_code=201)
def add_note(workspace_id: str, payload: ResearchNoteCreate, db: Session = Depends(get_db)) -> ResearchNoteRead:
    def _run():
        note = research_service.add_note(
            db, workspace_id, content=payload.content, linked_evidence_ids=payload.linked_evidence_ids
        )
        return _note_to_read(note)

    return _handle(_run)


@router.put("/api/research/workspaces/{workspace_id}/notes/{note_id}", response_model=ResearchNoteRead)
def update_note(
    workspace_id: str, note_id: str, payload: ResearchNoteUpdate, db: Session = Depends(get_db)
) -> ResearchNoteRead:
    def _run():
        note = research_service.update_note(
            db, workspace_id, note_id, content=payload.content, linked_evidence_ids=payload.linked_evidence_ids
        )
        return _note_to_read(note)

    return _handle(_run)


@router.post("/api/research/workspaces/{workspace_id}/notes/{note_id}/archive", response_model=ResearchNoteRead)
def archive_note(workspace_id: str, note_id: str, db: Session = Depends(get_db)) -> ResearchNoteRead:
    return _handle(lambda: _note_to_read(research_service.archive_note(db, workspace_id, note_id)))


# --- briefs --------------------------------------------------------------------


@router.get("/api/research/workspaces/{workspace_id}/briefs", response_model=list[ResearchBriefVersionSummary])
def list_briefs(workspace_id: str, db: Session = Depends(get_db)) -> list[ResearchBriefVersionSummary]:
    def _run():
        versions = research_service.list_brief_versions(db, workspace_id)
        return [
            ResearchBriefVersionSummary(
                id=v.id, version_number=v.version_number, source=v.source, status=v.status, generated_at=v.generated_at
            )
            for v in versions
        ]

    return _handle(_run)


@router.get(
    "/api/research/workspaces/{workspace_id}/briefs/{version_id}", response_model=ResearchBriefVersionRead
)
def get_brief(workspace_id: str, version_id: str, db: Session = Depends(get_db)) -> ResearchBriefVersionRead:
    def _run():
        version = research_service.get_brief_version(db, workspace_id, version_id)
        return _brief_to_read(db, version)

    return _handle(_run)


@router.post(
    "/api/research/workspaces/{workspace_id}/briefs/deterministic",
    response_model=ResearchBriefVersionRead,
    status_code=201,
)
def generate_deterministic_brief(workspace_id: str, db: Session = Depends(get_db)) -> ResearchBriefVersionRead:
    def _run():
        version = research_service.generate_deterministic_brief(db, workspace_id)
        return _brief_to_read(db, version)

    return _handle(_run)


@router.post(
    "/api/research/workspaces/{workspace_id}/briefs/draft",
    response_model=ResearchBriefVersionRead,
    status_code=201,
)
def draft_brief_with_model(
    workspace_id: str,
    db: Session = Depends(get_db),
    provider: AgentProvider = Depends(get_provider),
    settings: Settings = Depends(get_settings),
) -> ResearchBriefVersionRead:
    def _run():
        version = research_service.draft_brief_with_model(
            db, provider, workspace_id, timeout=settings.hermes_request_timeout_seconds
        )
        return _brief_to_read(db, version)

    return _handle(_run)
