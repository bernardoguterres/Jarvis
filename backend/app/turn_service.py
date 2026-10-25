"""Orchestrates one conversational turn: user message -> local context
construction -> Hermes -> assistant message, with a full agent_runs +
context_snapshots audit trail.

Context construction (app/context_builder.py) is entirely local and
model-independent; see CLAUDE.md §7 and docs/ARCHITECTURE.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

import logging

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import hooks
from app.config import Settings
from app.context_builder import ContextBuildError, ContextSnapshotData, build_context
from app.models import AgentRun, Conversation, Domain, Message
from app.models_memory import ContextSnapshot
from app.providers.base import AgentProvider, ProviderError, ProviderErrorCode
from app.recall_index_service import sync_recall

logger = logging.getLogger("jarvis.turns")


class ConversationNotFoundError(Exception):
    pass


@dataclass
class TurnOutcome:
    run: AgentRun
    user_message: Message
    assistant_message: Message | None


def _validate_additional_domains(db: Session, domain_ids: list[str]) -> None:
    for domain_id in domain_ids:
        if db.get(Domain, domain_id) is None:
            raise ContextBuildError(f"Unknown additional domain_id: {domain_id!r}")


def _persist_context_snapshot(db: Session, agent_run_id: str, snapshot: ContextSnapshotData) -> None:
    db.add(
        ContextSnapshot(
            agent_run_id=agent_run_id,
            active_domain_id=snapshot.active_domain_id,
            additional_domain_ids_json=json.dumps(snapshot.additional_domain_ids),
            global_memory_version_ids_json=json.dumps(snapshot.global_memory_version_ids),
            domain_memory_version_ids_json=json.dumps(snapshot.domain_memory_version_ids),
            domain_summary_version_ids_json=json.dumps(snapshot.domain_summary_version_ids),
            structured_record_ids_json=json.dumps(snapshot.structured_record_ids),
            recent_message_ids_json=json.dumps(snapshot.recent_message_ids),
            retrieval_query=snapshot.retrieval_query,
            retrieval_reasons_json=json.dumps(snapshot.retrieval_reasons),
            estimated_context_chars=snapshot.estimated_context_chars,
            document_chunk_ids_json=json.dumps(snapshot.document_chunk_ids),
            calendar_event_ids_json=json.dumps(snapshot.calendar_event_ids),
            google_health_summary_ids_json=json.dumps(snapshot.google_health_summary_ids),
        )
    )
    db.flush()


def send_turn(
    db: Session,
    provider: AgentProvider,
    settings: Settings,
    conversation_id: str,
    content: str,
    idempotency_key: str,
    additional_domain_ids: list[str] | None = None,
) -> TurnOutcome:
    additional_domain_ids = additional_domain_ids or []

    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise ConversationNotFoundError(conversation_id)

    # Idempotency, keyed by (conversation, idempotency_key):
    #   succeeded -> return the saved outcome, no new model call;
    #   running   -> another request with this key is still in flight,
    #                return it as-is (the client should wait, not resend);
    #   failed    -> this is an explicit retry: reuse the already-saved user
    #                message and call the provider again, so retrying never
    #                duplicates the user's message.
    existing_run = _find_run(db, conversation_id, idempotency_key)
    if existing_run is not None and existing_run.status != "failed":
        return _outcome_for(db, existing_run)

    # None for a general conversation (migration 0011): not a seventh
    # domain, just the absence of one.
    domain = db.get(Domain, conversation.domain_id) if conversation.domain_id is not None else None

    if existing_run is not None:
        # Claim the retry atomically so two concurrent retries with the same
        # key cannot both call the provider.
        claimed = db.execute(
            update(AgentRun)
            .where(AgentRun.id == existing_run.id, AgentRun.status == "failed")
            .values(
                status="running",
                error_code=None,
                error_summary=None,
                completed_at=None,
                started_at=datetime.now(timezone.utc),
            )
            .execution_options(synchronize_session=False)
        ).rowcount
        db.commit()
        db.refresh(existing_run)
        if claimed != 1:
            return _outcome_for(db, existing_run)
        run = existing_run
        user_message = db.get(Message, run.user_message_id)
        content = user_message.content
        # A retry rebuilds context from scratch; drop the failed attempt's
        # snapshot so the new one can take its place.
        db.query(ContextSnapshot).filter_by(agent_run_id=run.id).delete()
        db.commit()
    else:
        user_message = Message(conversation_id=conversation_id, role="user", content=content)
        db.add(user_message)
        db.flush()
        sync_recall(db, "message", user_message.id)

        run = AgentRun(
            conversation_id=conversation_id,
            user_message_id=user_message.id,
            provider=provider.name,
            model=settings.hermes_model,
            status="running",
            idempotency_key=idempotency_key,
        )
        db.add(run)
        try:
            db.flush()
            db.commit()
        except IntegrityError:
            # A concurrent request with the same key won the insert (unique
            # index on conversation_id + idempotency_key). Discard ours and
            # report theirs.
            db.rollback()
            winner = _find_run(db, conversation_id, idempotency_key)
            if winner is None:
                raise
            return _outcome_for(db, winner)

    run_id = run.id
    try:
        return _run_turn(db, provider, settings, conversation, domain, run, user_message, content, additional_domain_ids)
    except Exception:
        # Anything unexpected (a provider bug, a database error while saving
        # the reply) must not leave the run stuck in 'running' with the UI
        # unable to tell what happened. Record a sanitised failure; the user
        # message stays saved and a retry with the same key reuses it.
        db.rollback()
        logger.exception("Turn %s failed unexpectedly", run_id)
        run = db.get(AgentRun, run_id)
        run.status = "failed"
        run.error_code = ProviderErrorCode.INTERNAL_ERROR
        run.error_summary = "Jarvis hit an internal error while handling this reply. Your message was saved; retry to try again."
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(run)
        return TurnOutcome(run=run, user_message=db.get(Message, run.user_message_id), assistant_message=None)


def _find_run(db: Session, conversation_id: str, idempotency_key: str) -> AgentRun | None:
    return db.execute(
        select(AgentRun).where(
            AgentRun.conversation_id == conversation_id,
            AgentRun.idempotency_key == idempotency_key,
        )
    ).scalar_one_or_none()


def _outcome_for(db: Session, run: AgentRun) -> TurnOutcome:
    user_message = db.get(Message, run.user_message_id)
    assistant_message = db.get(Message, run.assistant_message_id) if run.assistant_message_id else None
    return TurnOutcome(run=run, user_message=user_message, assistant_message=assistant_message)


def fail_interrupted_runs(db: Session) -> int:
    """Startup sweep: a run still 'running' when the process starts was cut
    off by a crash, kill or quit before its reply was saved. Mark it failed
    with a clear reason so the conversation shows what happened and a retry
    (same idempotency key) can run it again."""
    stuck = db.execute(select(AgentRun).where(AgentRun.status == "running")).scalars().all()
    now = datetime.now(timezone.utc)
    for run in stuck:
        run.status = "failed"
        run.error_code = ProviderErrorCode.INTERRUPTED
        run.error_summary = "Jarvis stopped before this reply finished. Your message was saved; retry to try again."
        run.completed_at = now
    if stuck:
        db.commit()
    return len(stuck)


def _run_turn(
    db: Session,
    provider: AgentProvider,
    settings: Settings,
    conversation: Conversation,
    domain: Domain | None,
    run: AgentRun,
    user_message: Message,
    content: str,
    additional_domain_ids: list[str],
) -> TurnOutcome:
    conversation_id = conversation.id

    # Context construction must fail safely, before any model call, if it
    # fails at all. No assistant message is invented and the failure is
    # sanitised in the stored run.
    try:
        hook_outcomes = hooks.run_hooks(
            "before_context",
            hooks.HookContext(phase="before_context", db=db, domain_id=domain.id if domain is not None else None),
        )
        db.commit()
        blocked = next((o for o in hook_outcomes if not o.allowed), None)
        if blocked is not None:
            raise ContextBuildError(blocked.detail)

        _validate_additional_domains(db, additional_domain_ids)
        context = build_context(
            db,
            conversation=conversation,
            domain=domain,
            additional_domain_ids=additional_domain_ids,
            query_text=content,
            max_recent_messages=settings.hermes_max_context_messages,
        )
    except ContextBuildError as exc:
        run.status = "failed"
        run.error_code = "context_build_failed"
        run.error_summary = str(exc)
        run.completed_at = datetime.now(timezone.utc)
        db.add(run)
        db.commit()
        db.refresh(run)
        return TurnOutcome(run=run, user_message=user_message, assistant_message=None)

    _persist_context_snapshot(db, run.id, context.snapshot)
    db.commit()

    try:
        result = provider.send_turn(
            system_prompt=context.system_prompt,
            messages=context.history,
            timeout=settings.hermes_request_timeout_seconds,
        )
    except ProviderError as exc:
        run.status = "failed"
        run.error_code = exc.code
        run.error_summary = exc.summary
        run.completed_at = datetime.now(timezone.utc)
        db.add(run)
        db.commit()
        db.refresh(run)
        return TurnOutcome(run=run, user_message=user_message, assistant_message=None)

    assistant_message = Message(
        conversation_id=conversation_id,
        role="assistant",
        content=result.content,
        model_used=result.model,
    )
    db.add(assistant_message)
    db.flush()
    sync_recall(db, "message", assistant_message.id)

    run.status = "succeeded"
    run.assistant_message_id = assistant_message.id
    run.completed_at = datetime.now(timezone.utc)
    run.latency_ms = result.latency_ms
    run.input_tokens = result.usage.input_tokens
    run.output_tokens = result.usage.output_tokens
    run.total_tokens = result.usage.total_tokens
    run.external_run_id = result.external_run_id
    db.add(run)
    db.commit()
    db.refresh(run)
    db.refresh(assistant_message)

    return TurnOutcome(run=run, user_message=user_message, assistant_message=assistant_message)
