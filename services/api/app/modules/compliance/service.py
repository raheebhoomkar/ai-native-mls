"""Policy checks of a listing's title and remarks (Module 6b).

A scan runs the policy's rules, then asks a language model for what the patterns miss.
Findings are decision support: nothing here changes, hides or rejects a listing.
Scans are internal to the organisation that owns the listing.
"""

from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.modules.ai.models import AgentRun
from app.modules.ai.providers import ProviderError
from app.modules.audit import service as audit
from app.modules.compliance.policy import INDIA_POLICY, Policy, check_remarks
from app.modules.compliance.providers import DemoTextReviewer, GeminiTextReviewer, TextReviewer
from app.modules.compliance.schemas import ComplianceFinding, ComplianceScan, ModelFinding
from app.modules.jobs import service as jobs
from app.modules.jobs.models import Job
from app.modules.listings import service as listings
from app.modules.listings.models import Listing
from app.modules.organisations.deps import TenantContext

AGENT = "compliance"
AGENT_VERSION = "1"
MAX_ATTEMPTS = 3

Trigger = Literal["manual", "submitted"]


def get_policy() -> Policy:
    return INDIA_POLICY


def get_reviewer() -> TextReviewer:
    """Gemini when a key is set; otherwise the demo reviewer, which checks nothing."""
    settings = get_settings()
    if settings.gemini_api_key is None:
        return DemoTextReviewer()
    return GeminiTextReviewer(
        settings.gemini_api_key.get_secret_value(),
        settings.gemini_model,
        settings.ai_timeout_seconds,
    )


def _own_listing(session: Session, ctx: TenantContext, listing_id: UUID) -> Listing:
    listing = listings.get_listing(session, ctx, listing_id)  # 404 if not visible
    if listing.organisation_id != ctx.organisation_id:
        raise AppError(404, "not_found", "Listing not found.")
    return listing


def _in_progress(session: Session, listing_id: UUID) -> bool:
    return (
        session.scalar(
            select(AgentRun.id).where(
                AgentRun.listing_id == listing_id,
                AgentRun.agent == AGENT,
                AgentRun.status.in_(("queued", "running")),
            )
        )
        is not None
    )


def request_scan(session: Session, ctx: TenantContext, listing_id: UUID) -> AgentRun:
    """Queue a check of the listing's current title and remarks. Editors only."""
    listing = _scannable(session, ctx, listing_id)
    if _in_progress(session, listing.id):
        raise AppError(409, "scan_in_progress", "This listing is already being checked.")
    return _queue(session, ctx, listing, "manual")


def scan_on_submit(session: Session, ctx: TenantContext, listing_id: UUID) -> AgentRun | None:
    """The automatic check when a listing is submitted for review; skipped if one is running."""
    listing = _scannable(session, ctx, listing_id)
    return None if _in_progress(session, listing.id) else _queue(session, ctx, listing, "submitted")


def _scannable(session: Session, ctx: TenantContext, listing_id: UUID) -> Listing:
    listing = _own_listing(session, ctx, listing_id)
    if not listings.can_edit(ctx, listing):
        raise AppError(403, "forbidden", "You do not have permission to do this.")
    if listing.archived_at is not None:
        raise AppError(409, "listing_archived", "This listing is archived.")
    return listing


def _queue(session: Session, ctx: TenantContext, listing: Listing, trigger: Trigger) -> AgentRun:
    policy = get_policy()
    run = AgentRun(
        organisation_id=listing.organisation_id,
        listing_id=listing.id,
        requested_by_user_id=ctx.user.id,
        agent=AGENT,
        agent_version=AGENT_VERSION,
        # The text as it was when asked, so findings point into what was checked.
        inputs=[
            {
                "listing_version": listing.version,
                "trigger": trigger,
                "policy_id": policy.id,
                "policy_version": policy.version,
                "title": listing.title,
                "remarks": listing.remarks or "",
            }
        ],
        status="queued",
    )
    session.add(run)
    session.flush()
    job = jobs.enqueue(
        session,
        "compliance.scan",
        {"run_id": str(run.id)},
        organisation_id=listing.organisation_id,
        max_attempts=MAX_ATTEMPTS,
    )
    run.job_id = job.id
    session.flush()
    return run


def list_scans(session: Session, ctx: TenantContext, listing_id: UUID) -> Sequence[AgentRun]:
    """Newest first. Only the organisation that owns the listing sees its scans."""
    _own_listing(session, ctx, listing_id)
    return session.scalars(
        select(AgentRun)
        .where(AgentRun.listing_id == listing_id, AgentRun.agent == AGENT)
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
    ).all()


def record_requested(session: Session, ctx: TenantContext, run: AgentRun, ip: str | None) -> None:
    audit.record(
        session,
        "compliance.scan_requested",
        actor_user_id=ctx.user.id,
        organisation_id=ctx.organisation_id,
        target_type="agent_run",
        target_id=str(run.id),
        ip_address=ip,
        detail={
            "listing_id": str(run.listing_id),
            "trigger": run.inputs[0]["trigger"],
            "policy_id": run.inputs[0]["policy_id"],
            "policy_version": run.inputs[0]["policy_version"],
        },
    )


# --- Background job ------------------------------------------------------------------------


def rule_findings(policy: Policy, texts: dict[str, str]) -> list[ComplianceFinding]:
    titles = {rule.id: rule.title for rule in policy.rules}
    return [
        ComplianceFinding(
            field=field,
            rule_title=titles[f.rule_id],
            source="rule",
            **asdict(f),
        )
        for field, text in texts.items()
        for f in check_remarks(text, policy)
    ]


def model_findings(
    policy: Policy,
    texts: dict[str, str],
    found: Sequence[ModelFinding],
    known: Sequence[ComplianceFinding],
) -> tuple[list[ComplianceFinding], int]:
    """Model findings whose quote is in the text and whose rule exists, minus those a rule
    already reported at the same place. Returns them and how many were dropped as unusable.
    """
    rules = {rule.id: rule for rule in policy.rules}
    kept: list[ComplianceFinding] = []
    dropped = 0
    for item in found:
        text = texts.get(item.field, "")
        start = text.find(item.evidence)
        if start < 0:
            start = text.lower().find(item.evidence.lower())
        rule = rules.get(item.rule_id)
        if start < 0 or rule is None:
            dropped += 1
            continue
        end = start + len(item.evidence)
        if any(
            k.field == item.field and k.rule_id == rule.id and k.start < end and start < k.end
            for k in [*known, *kept]
        ):
            continue
        kept.append(
            ComplianceFinding(
                field=item.field,
                rule_id=rule.id,
                rule_title=rule.title,
                category=rule.category,
                # The policy sets severity; the model only says how sure it is.
                severity=rule.severity,
                confidence=item.confidence,
                evidence=text[start:end],
                start=start,
                end=end,
                explanation=item.explanation,
                suggestion=item.suggestion,
                source="model",
            )
        )
    return kept, dropped


def _fail_run(run: AgentRun, error: str) -> None:
    run.status = "failed"
    run.error = error
    run.finished_at = datetime.now(UTC)


def _scan_failed(session: Session, job: Job) -> None:
    run = session.get(AgentRun, UUID(job.payload["run_id"]))
    if run is not None and run.status in ("queued", "running"):
        run.attempts = job.attempts
        _fail_run(run, job.last_error or "The check failed.")


@jobs.handler("compliance.scan", on_failed=_scan_failed)
def run_scan(session: Session, job: Job) -> None:
    """A retryable model error re-raises until the last attempt; then the scan finishes with
    the rule check only and says the model check was not done.
    """
    run = session.get(AgentRun, UUID(job.payload["run_id"]))
    if run is None or run.status in ("succeeded", "failed"):
        return
    run.status = "running"
    run.started_at = datetime.now(UTC)
    run.attempts = job.attempts

    inputs = run.inputs[0]
    policy = get_policy()
    if (inputs["policy_id"], inputs["policy_version"]) != (policy.id, policy.version):
        _fail_run(run, "The policy changed after the check was requested. Run it again.")
        return
    texts = {field: inputs[field] for field in ("title", "remarks") if inputs[field].strip()}

    findings = rule_findings(policy, texts)
    run.provider, run.model, run.model_version = "rules", policy.version, None
    model_checked, model_note, dropped = False, None, 0
    try:
        result = get_reviewer().review(policy, texts)
    except ProviderError as error:
        if error.retryable and job.attempts < job.max_attempts:
            raise
        model_note = f"The language model check failed: {error}"
    else:
        if result.provider == "demo":
            run.provider, run.model = "demo", result.model
            model_note = "No language model is configured (demo mode); only the rules ran."
        else:
            run.provider, run.model, run.model_version = (
                result.provider,
                result.model,
                result.model_version,
            )
            extra, dropped = model_findings(policy, texts, result.findings, findings)
            findings += extra
            model_checked = True

    run.output = ComplianceScan(
        policy_id=policy.id,
        policy_version=policy.version,
        policy_name=policy.name,
        policy_notice=policy.notice,
        jurisdiction=policy.jurisdiction,
        findings=sorted(findings, key=lambda f: (f.field != "title", f.start, f.rule_id)),
        model_checked=model_checked,
        model_note=model_note,
        model_dropped=dropped,
    ).model_dump(mode="json")
    run.status = "succeeded"
    run.error = None
    run.finished_at = datetime.now(UTC)
