"""Phase 12F: Evidence-Based Decision Room HTTP surface, built on top of
Phase 12D Unified Recall and Phase 12E Research Workspaces. Evidence
search is read-only (delegates to `app.recall_service.search()`); every
other route here only ever mutates this feature's own local decision
state — never a Calendar/Health/memory mutation, never a tool, never
Hermes toolset configuration, never something that finalizes or executes
a decision on Jarvis's own initiative. `POST .../briefs/critique` is the
one route that reaches a model, and only via a single
`provider.send_turn()` call — see `app.decision_service.draft_critique_with_model`.
Every mutating route uses `PUT`/explicit `POST .../action` only — never
`PATCH`/`DELETE` — matching the backend's restricted, non-wildcard CORS
`allow_methods` (`GET`, `POST`, `PUT` — see D82/D99) and every other
Phase 8-12 router's own established convention.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app import decision_service, recall_service
from app.config import Settings, get_settings
from app.deps import get_db, get_provider
from app.models_decisions import (
    Decision,
    DecisionAssessment,
    DecisionBriefVersion,
    DecisionCriterion,
    DecisionEvidenceLink,
    DecisionFactor,
    DecisionFinalVersion,
    DecisionOption,
    DecisionOutcomeReview,
)
from app.providers.base import AgentProvider
from app.schemas_decisions import (
    AbandonRequest,
    CalibrationSummaryRead,
    DecideRequest,
    DecisionAssessmentRead,
    DecisionAssessmentSet,
    DecisionBriefVersionRead,
    DecisionBriefVersionSummary,
    DecisionCitationRead,
    DecisionCreate,
    DecisionCriterionCreate,
    DecisionCriterionRead,
    DecisionCriterionUpdate,
    DecisionEvidenceAdd,
    DecisionEvidenceImportFromResearch,
    DecisionEvidenceRead,
    DecisionEvidenceUpdate,
    DecisionFactorCreate,
    DecisionFactorRead,
    DecisionFactorResolve,
    DecisionFactorUpdate,
    DecisionFinalVersionRead,
    DecisionLinkWorkspaceRequest,
    DecisionModelMetaRead,
    DecisionOptionCreate,
    DecisionOptionRead,
    DecisionOptionUpdate,
    DecisionOutcomeReviewCreate,
    DecisionOutcomeReviewRead,
    DecisionRead,
    DecisionUpdate,
    ScoreBreakdownRead,
    SupersedeRequest,
)
from app.schemas_recall import RecallResultRead, RecallSearchRead

router = APIRouter(tags=["decisions"])


def _decision_to_read(session: Session, decision: Decision) -> DecisionRead:
    fields = decision_service.decision_summary_fields(session, decision)
    return DecisionRead(
        id=decision.id,
        title=decision.title,
        description=decision.description,
        domain_slug=fields["domain_slug"],
        research_workspace_id=decision.research_workspace_id,
        included_domain_slugs=fields["included_domain_slugs"],
        effective_domain_slugs=fields["effective_domain_slugs"],
        status=decision.status,
        review_date=decision.review_date,
        cost_of_delay_note=decision.cost_of_delay_note,
        info_confidence=decision.info_confidence,
        reversibility=decision.reversibility,
        supersedes_decision_id=decision.supersedes_decision_id,
        superseded_by_decision_id=decision.superseded_by_decision_id,
        abandoned_at=decision.abandoned_at,
        abandoned_reason=decision.abandoned_reason,
        option_count=fields["option_count"],
        criterion_count=fields["criterion_count"],
        evidence_count=fields["evidence_count"],
        latest_brief_version=fields["latest_brief_version"],
        is_decided=fields["is_decided"],
        review_due=fields["review_due"],
        created_at=decision.created_at,
        updated_at=decision.updated_at,
    )


def _option_to_read(option: DecisionOption) -> DecisionOptionRead:
    return DecisionOptionRead(
        id=option.id, decision_id=option.decision_id, name=option.name, description=option.description,
        benefits=option.benefits, costs=option.costs, risks=option.risks, reversibility=option.reversibility,
        status=option.status, rank=option.rank, created_at=option.created_at, updated_at=option.updated_at,
    )


def _criterion_to_read(criterion: DecisionCriterion) -> DecisionCriterionRead:
    return DecisionCriterionRead(
        id=criterion.id, decision_id=criterion.decision_id, name=criterion.name, description=criterion.description,
        weight=criterion.weight, rank=criterion.rank, created_at=criterion.created_at, updated_at=criterion.updated_at,
    )


def _assessment_to_read(a: DecisionAssessment) -> DecisionAssessmentRead:
    return DecisionAssessmentRead(
        id=a.id, option_id=a.option_id, criterion_id=a.criterion_id, score=a.score, note=a.note,
        created_at=a.created_at, updated_at=a.updated_at,
    )


def _evidence_to_read(session: Session, link: DecisionEvidenceLink) -> DecisionEvidenceRead:
    fields = decision_service.evidence_read_fields(session, link)
    return DecisionEvidenceRead(
        id=link.id, decision_id=link.decision_id, source_type=link.source_type, source_id=link.source_id,
        research_evidence_id=link.research_evidence_id, linked_option_id=link.linked_option_id,
        domain_slug=link.domain_slug, title_snapshot=link.title_snapshot, snippet_snapshot=link.snippet_snapshot,
        occurred_at_snapshot=link.occurred_at_snapshot, stance=link.stance, note=link.note, status=link.status,
        available=fields["available"], unavailable_reason=fields["unavailable_reason"],
        link_target=fields["link_target"], added_at=link.added_at, updated_at=link.updated_at,
    )


def _factor_to_read(f: DecisionFactor) -> DecisionFactorRead:
    return DecisionFactorRead(
        id=f.id, decision_id=f.decision_id, kind=f.kind, content=f.content, linked_option_id=f.linked_option_id,
        status=f.status, resolution_note=f.resolution_note, resolved_at=f.resolved_at,
        created_at=f.created_at, updated_at=f.updated_at,
    )


def _brief_to_read(session: Session, version: DecisionBriefVersion) -> DecisionBriefVersionRead:
    citations = [DecisionCitationRead(**c) for c in decision_service.citation_reads(session, version)]
    model_meta = DecisionModelMetaRead(**json.loads(version.model_meta_json)) if version.model_meta_json else None
    return DecisionBriefVersionRead(
        id=version.id, decision_id=version.decision_id, version_number=version.version_number,
        source=version.source, status=version.status, title=version.title, sections_json=version.sections_json,
        citations=citations, validation_issues=json.loads(version.validation_json), model_meta=model_meta,
        generated_at=version.generated_at, created_at=version.created_at,
    )


def _final_version_to_read(session: Session, v: DecisionFinalVersion) -> DecisionFinalVersionRead:
    option = session.get(DecisionOption, v.selected_option_id)
    return DecisionFinalVersionRead(
        id=v.id, decision_id=v.decision_id, version_number=v.version_number, selected_option_id=v.selected_option_id,
        selected_option_name=option.name if option else "(unknown option)", rationale=v.rationale,
        decision_confidence=v.decision_confidence, decided_at=v.decided_at, created_at=v.created_at,
    )


def _outcome_review_to_read(r: DecisionOutcomeReview) -> DecisionOutcomeReviewRead:
    return DecisionOutcomeReviewRead(
        id=r.id, decision_id=r.decision_id, decision_final_version_id=r.decision_final_version_id,
        what_happened=r.what_happened, intended_outcome_achieved=r.intended_outcome_achieved,
        confidence_was_appropriate=r.confidence_was_appropriate, would_decide_same_again=r.would_decide_same_again,
        lessons_learned=r.lessons_learned, reviewed_at=r.reviewed_at, created_at=r.created_at,
    )


def _handle(fn):
    try:
        return fn()
    except decision_service.DecisionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except decision_service.DecisionModelError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except decision_service.DecisionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --- decisions -------------------------------------------------------------------


@router.post("/api/decisions", response_model=DecisionRead, status_code=201)
def create_decision(payload: DecisionCreate, db: Session = Depends(get_db)) -> DecisionRead:
    def _run():
        decision = decision_service.create_decision(
            db, title=payload.title, description=payload.description, domain_slug=payload.domain_slug,
            research_workspace_id=payload.research_workspace_id,
            included_domain_slugs_arg=payload.included_domain_slugs,
        )
        return _decision_to_read(db, decision)

    return _handle(_run)


@router.get("/api/decisions", response_model=list[DecisionRead])
def list_decisions(status: str | None = Query(default=None), db: Session = Depends(get_db)) -> list[DecisionRead]:
    from app.models_decisions import DECISION_STATUSES

    if status is not None and status not in DECISION_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {DECISION_STATUSES}.")
    decisions = decision_service.list_decisions(db, status=status)
    return [_decision_to_read(db, d) for d in decisions]


@router.get("/api/decisions/{decision_id}", response_model=DecisionRead)
def get_decision(decision_id: str, db: Session = Depends(get_db)) -> DecisionRead:
    return _handle(lambda: _decision_to_read(db, decision_service.get_decision(db, decision_id)))


@router.put("/api/decisions/{decision_id}", response_model=DecisionRead)
def update_decision(decision_id: str, payload: DecisionUpdate, db: Session = Depends(get_db)) -> DecisionRead:
    fields = payload.model_dump(exclude_unset=True)

    def _run():
        decision = decision_service.update_decision(
            db, decision_id,
            title=fields.get("title"), description=fields.get("description"),
            included_domain_slugs_arg=fields.get("included_domain_slugs"),
            review_date=fields.get("review_date"), review_date_set="review_date" in fields,
            cost_of_delay_note=fields.get("cost_of_delay_note"), cost_of_delay_note_set="cost_of_delay_note" in fields,
            info_confidence=fields.get("info_confidence"), info_confidence_set="info_confidence" in fields,
            reversibility=fields.get("reversibility"), reversibility_set="reversibility" in fields,
        )
        return _decision_to_read(db, decision)

    return _handle(_run)


@router.put("/api/decisions/{decision_id}/research-workspace", response_model=DecisionRead)
def link_research_workspace(
    decision_id: str, payload: DecisionLinkWorkspaceRequest, db: Session = Depends(get_db)
) -> DecisionRead:
    def _run():
        decision = decision_service.link_research_workspace(db, decision_id, payload.research_workspace_id)
        return _decision_to_read(db, decision)

    return _handle(_run)


@router.post("/api/decisions/{decision_id}/start-evaluating", response_model=DecisionRead)
def start_evaluating(decision_id: str, db: Session = Depends(get_db)) -> DecisionRead:
    return _handle(lambda: _decision_to_read(db, decision_service.start_evaluating(db, decision_id)))


@router.post("/api/decisions/{decision_id}/decide", response_model=DecisionRead)
def decide(decision_id: str, payload: DecideRequest, db: Session = Depends(get_db)) -> DecisionRead:
    def _run():
        decision = decision_service.decide(
            db, decision_id, selected_option_id=payload.selected_option_id, rationale=payload.rationale,
            decision_confidence=payload.decision_confidence,
        )
        return _decision_to_read(db, decision)

    return _handle(_run)


@router.post("/api/decisions/{decision_id}/reopen", response_model=DecisionRead)
def reopen(decision_id: str, db: Session = Depends(get_db)) -> DecisionRead:
    return _handle(lambda: _decision_to_read(db, decision_service.reopen(db, decision_id)))


@router.post("/api/decisions/{decision_id}/supersede", response_model=DecisionRead)
def supersede(decision_id: str, payload: SupersedeRequest, db: Session = Depends(get_db)) -> DecisionRead:
    def _run():
        decision = decision_service.supersede(db, decision_id, payload.new_decision_id)
        return _decision_to_read(db, decision)

    return _handle(_run)


@router.post("/api/decisions/{decision_id}/abandon", response_model=DecisionRead)
def abandon(decision_id: str, payload: AbandonRequest, db: Session = Depends(get_db)) -> DecisionRead:
    def _run():
        decision = decision_service.abandon(db, decision_id, reason=payload.reason)
        return _decision_to_read(db, decision)

    return _handle(_run)


# --- evidence discovery (read-only, delegates to Recall) -----------------------


@router.get("/api/decisions/{decision_id}/evidence/search", response_model=RecallSearchRead)
def search_evidence_candidates(
    decision_id: str, q: str = Query(default=""), source_types: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=recall_service.RECALL_MAX_LIMIT), offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> RecallSearchRead:
    types = [s.strip() for s in source_types.split(",") if s.strip()] if source_types is not None else None

    def _run():
        result = decision_service.search_decision_evidence(db, decision_id, q, source_types=types, limit=limit, offset=offset)
        return RecallSearchRead(
            query=result.query,
            results=[
                RecallResultRead(
                    source_type=r.source_type, source_id=r.source_id, domain_slug=r.domain_slug, title=r.title,
                    snippet_html=r.snippet_html, occurred_at=r.occurred_at, link_target=r.link_target,
                    available=r.available, unavailable_reason=r.unavailable_reason,
                )
                for r in result.results
            ],
            total_considered=result.total_considered, limit=result.limit, offset=result.offset,
            has_more=result.has_more, partial_failures=result.partial_failures,
        )

    return _handle(_run)


# --- options -----------------------------------------------------------------


@router.get("/api/decisions/{decision_id}/options", response_model=list[DecisionOptionRead])
def list_options(decision_id: str, db: Session = Depends(get_db)) -> list[DecisionOptionRead]:
    def _run():
        decision_service.get_decision(db, decision_id)
        return [_option_to_read(o) for o in decision_service.list_options(db, decision_id)]

    return _handle(_run)


@router.post("/api/decisions/{decision_id}/options", response_model=DecisionOptionRead, status_code=201)
def add_option(decision_id: str, payload: DecisionOptionCreate, db: Session = Depends(get_db)) -> DecisionOptionRead:
    def _run():
        option = decision_service.add_option(
            db, decision_id, name=payload.name, description=payload.description, benefits=payload.benefits,
            costs=payload.costs, risks=payload.risks, reversibility=payload.reversibility,
        )
        return _option_to_read(option)

    return _handle(_run)


@router.put("/api/decisions/{decision_id}/options/{option_id}", response_model=DecisionOptionRead)
def update_option(
    decision_id: str, option_id: str, payload: DecisionOptionUpdate, db: Session = Depends(get_db)
) -> DecisionOptionRead:
    fields = payload.model_dump(exclude_unset=True)

    def _run():
        option = decision_service.update_option(
            db, decision_id, option_id, name=fields.get("name"), description=fields.get("description"),
            benefits=fields.get("benefits"), costs=fields.get("costs"), risks=fields.get("risks"),
            reversibility=fields.get("reversibility"), reversibility_set="reversibility" in fields,
            status=fields.get("status"),
        )
        return _option_to_read(option)

    return _handle(_run)


# --- criteria ------------------------------------------------------------------


@router.get("/api/decisions/{decision_id}/criteria", response_model=list[DecisionCriterionRead])
def list_criteria(decision_id: str, db: Session = Depends(get_db)) -> list[DecisionCriterionRead]:
    def _run():
        decision_service.get_decision(db, decision_id)
        return [_criterion_to_read(c) for c in decision_service.list_criteria(db, decision_id)]

    return _handle(_run)


@router.post("/api/decisions/{decision_id}/criteria", response_model=DecisionCriterionRead, status_code=201)
def add_criterion(decision_id: str, payload: DecisionCriterionCreate, db: Session = Depends(get_db)) -> DecisionCriterionRead:
    def _run():
        criterion = decision_service.add_criterion(
            db, decision_id, name=payload.name, description=payload.description, weight=payload.weight
        )
        return _criterion_to_read(criterion)

    return _handle(_run)


@router.put("/api/decisions/{decision_id}/criteria/{criterion_id}", response_model=DecisionCriterionRead)
def update_criterion(
    decision_id: str, criterion_id: str, payload: DecisionCriterionUpdate, db: Session = Depends(get_db)
) -> DecisionCriterionRead:
    def _run():
        criterion = decision_service.update_criterion(
            db, decision_id, criterion_id, name=payload.name, description=payload.description, weight=payload.weight
        )
        return _criterion_to_read(criterion)

    return _handle(_run)


@router.post("/api/decisions/{decision_id}/criteria/{criterion_id}/remove", status_code=204, response_model=None)
def remove_criterion(decision_id: str, criterion_id: str, db: Session = Depends(get_db)) -> None:
    return _handle(lambda: decision_service.remove_criterion(db, decision_id, criterion_id))


# --- assessments ---------------------------------------------------------------


@router.get("/api/decisions/{decision_id}/assessments", response_model=list[DecisionAssessmentRead])
def list_assessments(decision_id: str, db: Session = Depends(get_db)) -> list[DecisionAssessmentRead]:
    def _run():
        decision_service.get_decision(db, decision_id)
        return [_assessment_to_read(a) for a in decision_service.list_assessments(db, decision_id)]

    return _handle(_run)


@router.put("/api/decisions/{decision_id}/assessments", response_model=DecisionAssessmentRead)
def set_assessment(decision_id: str, payload: DecisionAssessmentSet, db: Session = Depends(get_db)) -> DecisionAssessmentRead:
    def _run():
        assessment = decision_service.set_assessment(
            db, decision_id, option_id=payload.option_id, criterion_id=payload.criterion_id,
            score=payload.score, note=payload.note,
        )
        return _assessment_to_read(assessment)

    return _handle(_run)


@router.get("/api/decisions/{decision_id}/score-breakdown", response_model=ScoreBreakdownRead)
def get_score_breakdown(decision_id: str, db: Session = Depends(get_db)) -> ScoreBreakdownRead:
    def _run():
        decision_service.get_decision(db, decision_id)
        options = decision_service.list_options(db, decision_id)
        criteria = decision_service.list_criteria(db, decision_id)
        assessments = decision_service.list_assessments(db, decision_id)
        breakdown = decision_service.compute_score_breakdown(options, criteria, assessments)
        return ScoreBreakdownRead(
            options=breakdown.options, ranked_option_ids=breakdown.ranked_option_ids, tied=breakdown.tied,
            sensitivity_warnings=breakdown.sensitivity_warnings, incomplete=breakdown.incomplete,
        )

    return _handle(_run)


# --- evidence --------------------------------------------------------------------


@router.get("/api/decisions/{decision_id}/evidence", response_model=list[DecisionEvidenceRead])
def list_evidence(decision_id: str, db: Session = Depends(get_db)) -> list[DecisionEvidenceRead]:
    def _run():
        decision_service.get_decision(db, decision_id)
        return [_evidence_to_read(db, e) for e in decision_service.list_evidence(db, decision_id)]

    return _handle(_run)


@router.post("/api/decisions/{decision_id}/evidence", response_model=DecisionEvidenceRead, status_code=201)
def add_evidence(decision_id: str, payload: DecisionEvidenceAdd, db: Session = Depends(get_db)) -> DecisionEvidenceRead:
    def _run():
        link = decision_service.add_evidence(
            db, decision_id, source_type=payload.source_type, source_id=payload.source_id, stance=payload.stance,
            note=payload.note, linked_option_id=payload.linked_option_id,
        )
        return _evidence_to_read(db, link)

    return _handle(_run)


@router.post("/api/decisions/{decision_id}/evidence/import-research", response_model=DecisionEvidenceRead, status_code=201)
def import_research_evidence(
    decision_id: str, payload: DecisionEvidenceImportFromResearch, db: Session = Depends(get_db)
) -> DecisionEvidenceRead:
    def _run():
        link = decision_service.import_research_evidence(
            db, decision_id, payload.research_evidence_id, stance=payload.stance,
            linked_option_id=payload.linked_option_id,
        )
        return _evidence_to_read(db, link)

    return _handle(_run)


@router.put("/api/decisions/{decision_id}/evidence/{link_id}", response_model=DecisionEvidenceRead)
def update_evidence(
    decision_id: str, link_id: str, payload: DecisionEvidenceUpdate, db: Session = Depends(get_db)
) -> DecisionEvidenceRead:
    fields = payload.model_dump(exclude_unset=True)

    def _run():
        link = decision_service.update_evidence(
            db, decision_id, link_id, stance=fields.get("stance"), note=fields.get("note"),
            linked_option_id=fields.get("linked_option_id"), linked_option_id_set="linked_option_id" in fields,
        )
        return _evidence_to_read(db, link)

    return _handle(_run)


@router.post("/api/decisions/{decision_id}/evidence/{link_id}/remove", response_model=DecisionEvidenceRead)
def remove_evidence(decision_id: str, link_id: str, db: Session = Depends(get_db)) -> DecisionEvidenceRead:
    return _handle(lambda: _evidence_to_read(db, decision_service.remove_evidence(db, decision_id, link_id)))


# --- factors: assumptions / risks / unknowns ------------------------------------


@router.get("/api/decisions/{decision_id}/factors", response_model=list[DecisionFactorRead])
def list_factors(decision_id: str, kind: str | None = Query(default=None), db: Session = Depends(get_db)) -> list[DecisionFactorRead]:
    def _run():
        decision_service.get_decision(db, decision_id)
        return [_factor_to_read(f) for f in decision_service.list_factors(db, decision_id, kind=kind)]

    return _handle(_run)


@router.post("/api/decisions/{decision_id}/factors", response_model=DecisionFactorRead, status_code=201)
def add_factor(decision_id: str, payload: DecisionFactorCreate, db: Session = Depends(get_db)) -> DecisionFactorRead:
    def _run():
        factor = decision_service.add_factor(
            db, decision_id, kind=payload.kind, content=payload.content, linked_option_id=payload.linked_option_id
        )
        return _factor_to_read(factor)

    return _handle(_run)


@router.put("/api/decisions/{decision_id}/factors/{factor_id}", response_model=DecisionFactorRead)
def update_factor(
    decision_id: str, factor_id: str, payload: DecisionFactorUpdate, db: Session = Depends(get_db)
) -> DecisionFactorRead:
    fields = payload.model_dump(exclude_unset=True)

    def _run():
        factor = decision_service.update_factor(
            db, decision_id, factor_id, content=fields.get("content"),
            linked_option_id=fields.get("linked_option_id"), linked_option_id_set="linked_option_id" in fields,
        )
        return _factor_to_read(factor)

    return _handle(_run)


@router.post("/api/decisions/{decision_id}/factors/{factor_id}/resolve", response_model=DecisionFactorRead)
def resolve_factor(
    decision_id: str, factor_id: str, payload: DecisionFactorResolve, db: Session = Depends(get_db)
) -> DecisionFactorRead:
    def _run():
        factor = decision_service.resolve_factor(db, decision_id, factor_id, resolution_note=payload.resolution_note)
        return _factor_to_read(factor)

    return _handle(_run)


# --- briefs (deterministic + model critique) ------------------------------------


@router.get("/api/decisions/{decision_id}/briefs", response_model=list[DecisionBriefVersionSummary])
def list_briefs(decision_id: str, db: Session = Depends(get_db)) -> list[DecisionBriefVersionSummary]:
    def _run():
        versions = decision_service.list_brief_versions(db, decision_id)
        return [
            DecisionBriefVersionSummary(id=v.id, version_number=v.version_number, source=v.source, status=v.status, generated_at=v.generated_at)
            for v in versions
        ]

    return _handle(_run)


@router.get("/api/decisions/{decision_id}/briefs/{version_id}", response_model=DecisionBriefVersionRead)
def get_brief(decision_id: str, version_id: str, db: Session = Depends(get_db)) -> DecisionBriefVersionRead:
    def _run():
        version = decision_service.get_brief_version(db, decision_id, version_id)
        return _brief_to_read(db, version)

    return _handle(_run)


@router.post("/api/decisions/{decision_id}/briefs/deterministic", response_model=DecisionBriefVersionRead, status_code=201)
def generate_deterministic_brief(decision_id: str, db: Session = Depends(get_db)) -> DecisionBriefVersionRead:
    def _run():
        version = decision_service.generate_deterministic_brief(db, decision_id)
        return _brief_to_read(db, version)

    return _handle(_run)


@router.post("/api/decisions/{decision_id}/briefs/critique", response_model=DecisionBriefVersionRead, status_code=201)
def draft_critique_with_model(
    decision_id: str, db: Session = Depends(get_db), provider: AgentProvider = Depends(get_provider),
    settings: Settings = Depends(get_settings),
) -> DecisionBriefVersionRead:
    def _run():
        version = decision_service.draft_critique_with_model(
            db, provider, decision_id, timeout=settings.hermes_request_timeout_seconds
        )
        return _brief_to_read(db, version)

    return _handle(_run)


# --- final decision + outcome review ----------------------------------------------


@router.get("/api/decisions/{decision_id}/final-versions", response_model=list[DecisionFinalVersionRead])
def list_final_versions(decision_id: str, db: Session = Depends(get_db)) -> list[DecisionFinalVersionRead]:
    def _run():
        return [_final_version_to_read(db, v) for v in decision_service.list_final_versions(db, decision_id)]

    return _handle(_run)


@router.get("/api/decisions/{decision_id}/outcome-reviews", response_model=list[DecisionOutcomeReviewRead])
def list_outcome_reviews(decision_id: str, db: Session = Depends(get_db)) -> list[DecisionOutcomeReviewRead]:
    def _run():
        return [_outcome_review_to_read(r) for r in decision_service.list_outcome_reviews(db, decision_id)]

    return _handle(_run)


@router.post("/api/decisions/{decision_id}/outcome-reviews", response_model=DecisionOutcomeReviewRead, status_code=201)
def add_outcome_review(
    decision_id: str, payload: DecisionOutcomeReviewCreate, db: Session = Depends(get_db)
) -> DecisionOutcomeReviewRead:
    def _run():
        review = decision_service.add_outcome_review(
            db, decision_id, decision_final_version_id=payload.decision_final_version_id,
            what_happened=payload.what_happened, intended_outcome_achieved=payload.intended_outcome_achieved,
            confidence_was_appropriate=payload.confidence_was_appropriate,
            would_decide_same_again=payload.would_decide_same_again, lessons_learned=payload.lessons_learned,
        )
        return _outcome_review_to_read(review)

    return _handle(_run)


@router.get("/api/decisions-calibration-summary", response_model=CalibrationSummaryRead)
def get_calibration_summary(db: Session = Depends(get_db)) -> CalibrationSummaryRead:
    summary = decision_service.calibration_summary(db)
    return CalibrationSummaryRead(
        reviewed_count=summary.reviewed_count, minimum_sample=summary.minimum_sample,
        has_enough_data=summary.has_enough_data, confidence_appropriate_rate=summary.confidence_appropriate_rate,
        would_decide_same_rate=summary.would_decide_same_rate, outcome_achieved_rate=summary.outcome_achieved_rate,
    )
