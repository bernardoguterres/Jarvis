"""Manual, versioned domain summaries.

Summaries are never auto-regenerated after messages in this phase — only
explicit create/edit actions produce a new version (CLAUDE.md/ROADMAP Phase 4
scope).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Domain
from app.models_memory import DomainSummary, DomainSummaryVersion


class DomainSummaryError(Exception):
    pass


def get_or_create_summary_slot(session: Session, domain_id: str) -> DomainSummary:
    summary = session.execute(
        select(DomainSummary).where(DomainSummary.domain_id == domain_id)
    ).scalar_one_or_none()
    if summary is not None:
        return summary
    if session.get(Domain, domain_id) is None:
        raise DomainSummaryError(f"Unknown domain_id: {domain_id!r}")
    summary = DomainSummary(domain_id=domain_id)
    session.add(summary)
    session.flush()
    return summary


def set_domain_summary(
    session: Session, domain_id: str, content: str, *, source: str = "manual"
) -> DomainSummary:
    """Creates a new immutable version and makes it current. Works for both
    the first summary and subsequent edits."""
    summary = get_or_create_summary_slot(session, domain_id)

    latest_version_number = (
        session.execute(
            select(DomainSummaryVersion.version_number)
            .where(DomainSummaryVersion.domain_summary_id == summary.id)
            .order_by(DomainSummaryVersion.version_number.desc())
            .limit(1)
        ).scalar_one_or_none()
        or 0
    )

    version = DomainSummaryVersion(
        domain_summary_id=summary.id,
        version_number=latest_version_number + 1,
        content=content,
        source=source,
    )
    session.add(version)
    session.flush()

    summary.current_version_id = version.id
    session.commit()
    session.refresh(summary)
    return summary


def clear_domain_summary(session: Session, domain_id: str) -> DomainSummary:
    """Archives the current summary by pointing at no current version, while
    keeping full version history intact."""
    summary = get_or_create_summary_slot(session, domain_id)
    summary.current_version_id = None
    session.commit()
    session.refresh(summary)
    return summary


def get_summary_history(session: Session, domain_id: str) -> list[DomainSummaryVersion]:
    summary = session.execute(
        select(DomainSummary).where(DomainSummary.domain_id == domain_id)
    ).scalar_one_or_none()
    if summary is None:
        return []
    return list(
        session.execute(
            select(DomainSummaryVersion)
            .where(DomainSummaryVersion.domain_summary_id == summary.id)
            .order_by(DomainSummaryVersion.version_number)
        )
        .scalars()
        .all()
    )
