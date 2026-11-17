"""Policy checks of a listing's title and remarks (Module 6b).

A scan runs the policy's rules, then asks a language model for what the patterns miss.
Findings are decision support: nothing here changes, hides or rejects a listing.
Scans are internal to the organisation that owns the listing.
"""

from collections.abc import Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass
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
from app.modules.compliance.schemas import (
    ComplianceFinding,
    ComplianceScan,
    ModelFinding,
    ReviewState,
)
from app.modules.jobs import service as jobs
from app.modules.jobs.models import Job
from app.modules.listings import service as listings
from app.modules.listings.models import Listing
from app.modules.organisations.deps import TenantContext
from app.modules.review import service as review
from app.modules.review.models import ReviewDecision, ReviewTask

AGENT = "compliance"
AGENT_VERSION = "1"
MAX_ATTEMPTS = 3
REVIEW_SUBJECT = "compliance_scan"

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
    return any(
        stalled(session, run) is None
        for run in session.scalars(
            select(AgentRun).where(
                AgentRun.listing_id == listing_id,
                AgentRun.agent == AGENT,
                AgentRun.status.in_(("queued", "running")),
            )
        )
    )


def stalled(session: Session, run: AgentRun) -> str | None:
    """Why an unfinished scan will never finish: its job failed without reaching the handler,
    for example on a worker still running older code. None when it may still finish.
    """
    if run.status not in ("queued", "running") or run.job_id is None:
        return None
    job = session.get(Job, run.job_id)
    if job is None or job.status != "failed":
        return None
    return job.last_error or "The check stopped."


def request_scan(
    session: Session, ctx: TenantContext, listing_id: UUID
) -> tuple[Listing, AgentRun]:
    """Queue a check of the listing's current title and remarks. Editors only."""
    listing = _scannable(session, ctx, listing_id)
    if _in_progress(session, listing.id):
        raise AppError(409, "scan_in_progress", "This listing is already being checked.")
    return listing, _queue(session, ctx, listing, "manual")


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
        # Set here, not by the database, so scans in one transaction still have an order.
        created_at=datetime.now(UTC),
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


def list_scans(
    session: Session, ctx: TenantContext, listing_id: UUID
) -> tuple[Listing, Sequence[AgentRun]]:
    """Newest first. Only the organisation that owns the listing sees its scans."""
    listing = _own_listing(session, ctx, listing_id)
    return listing, session.scalars(
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
    if _supersede(session, run) and findings:
        review.open_task(
            session,
            organisation_id=run.organisation_id,
            subject_type=REVIEW_SUBJECT,
            subject_id=str(run.id),
        )


def _supersede(session: Session, run: AgentRun) -> bool:
    """Close the reviews of the listing's older scans. False when a newer scan has already
    finished (this one ran late after retries), so this one gets no review.
    """
    others = session.scalars(
        select(AgentRun).where(
            AgentRun.listing_id == run.listing_id, AgentRun.agent == AGENT, AgentRun.id != run.id
        )
    ).all()
    if any(o.created_at > run.created_at and o.status == "succeeded" for o in others):
        return False
    older = [str(o.id) for o in others if o.created_at < run.created_at]
    for task in session.scalars(
        select(ReviewTask).where(
            ReviewTask.subject_type == REVIEW_SUBJECT,
            ReviewTask.subject_id.in_(older),
            ReviewTask.status == "open",
        )
    ):
        review.close(task)
    return True


# --- Review and appeal ---------------------------------------------------------------------
#
# Item keys of a scan's review task, per finding index i: "i" (the reviewer's decision),
# "i:appeal" (the listing agent's appeal) and "i:appeal_decision" (a second reviewer's ruling).

FindingDecision = Literal["accepted", "dismissed", "edits_requested"]
AppealDecision = Literal["upheld", "overturned"]
APPEALABLE = ("accepted", "edits_requested")
# The decision row, with the scan and finding it is about (for the audit record).
type Decided = tuple[AgentRun, ComplianceFinding, ReviewDecision]


@dataclass
class FindingReview:
    decision: ReviewDecision | None = None
    appeal: ReviewDecision | None = None
    appeal_decision: ReviewDecision | None = None

    @property
    def state(self) -> ReviewState:
        if self.appeal_decision:
            return self.appeal_decision.decision  # type: ignore[return-value]  # upheld, overturned
        if self.appeal:
            return "appealed"
        return self.decision.decision if self.decision else "open"  # type: ignore[return-value]


def can_review(ctx: TenantContext, listing: Listing) -> bool:
    """Approvers of the owning organisation, except the listing's own agent."""
    return (
        listing.organisation_id == ctx.organisation_id
        and ctx.has("listing:publish")
        and listing.listing_agent_user_id != ctx.user.id
    )


def can_appeal(ctx: TenantContext, listing: Listing) -> bool:
    return listing.organisation_id == ctx.organisation_id and (
        listing.listing_agent_user_id == ctx.user.id
    )


def findings_of(run: AgentRun) -> list[ComplianceFinding]:
    return ComplianceScan.model_validate(run.output).findings if run.output else []


def reviews(
    task: ReviewTask | None, rows: Sequence[ReviewDecision], count: int
) -> list[FindingReview]:
    """One entry per finding, built from the task's decision rows."""
    result = [FindingReview() for _ in range(count)]
    for row in rows:
        if row.task_id != (task.id if task else None) or row.item_key is None:
            continue
        index, _, part = row.item_key.partition(":")
        if index.isdigit() and int(index) < count:
            setattr(result[int(index)], part or "decision", row)
    return result


def review_of(session: Session, run: AgentRun) -> tuple[ReviewTask | None, list[FindingReview]]:
    task = review.get_task_for(session, REVIEW_SUBJECT, str(run.id))
    rows = review.decisions_for(session, [task.id]) if task else []
    return task, reviews(task, rows, len(findings_of(run)))


def _finding(
    session: Session, ctx: TenantContext, run_id: UUID, index: int
) -> tuple[AgentRun, Listing, ReviewTask, ComplianceFinding, FindingReview]:
    run = session.get(AgentRun, run_id)
    listing = None
    if run is not None and run.agent == AGENT:
        with suppress(AppError):  # same answer whether the scan exists or not
            listing = _own_listing(session, ctx, run.listing_id)
    findings = findings_of(run) if run and listing else []
    if run is None or listing is None or not 0 <= index < len(findings):
        raise AppError(404, "not_found", "Finding not found.")
    task, finding_reviews = review_of(session, run)
    if task is None or task.status != "open":
        raise AppError(409, "scan_superseded", "A newer check of this listing replaced this one.")
    return run, listing, task, findings[index], finding_reviews[index]


def decide_finding(
    session: Session,
    ctx: TenantContext,
    run_id: UUID,
    index: int,
    *,
    decision: FindingDecision,
    note: str | None,
) -> Decided:
    """Accept (a real problem), dismiss (not a problem) or ask for edits (note required)."""
    run, listing, task, finding, _ = _finding(session, ctx, run_id, index)
    if not can_review(ctx, listing):
        raise AppError(
            403, "forbidden", "Only an approver other than the listing's agent may review."
        )
    note = (note or "").strip() or None
    if decision == "edits_requested" and note is None:
        raise AppError(422, "note_required", "Say what should change.")
    return (
        run,
        finding,
        review.decide(
            session,
            task,
            item_key=str(index),
            decision=decision,
            suggested=finding.model_dump(mode="json"),
            final=None,
            note=note,
            user_id=ctx.user.id,
        ),
    )


def appeal(
    session: Session, ctx: TenantContext, run_id: UUID, index: int, *, reason: str
) -> Decided:
    """The listing agent disputes an accepted finding or a request for edits, once."""
    run, listing, task, finding, current = _finding(session, ctx, run_id, index)
    if not can_appeal(ctx, listing):
        raise AppError(403, "forbidden", "Only the listing's agent may appeal.")
    if not reason.strip():
        raise AppError(422, "reason_required", "Say why the decision is wrong.")
    if current.decision is None or current.decision.decision not in APPEALABLE:
        raise AppError(
            409,
            "not_appealable",
            "Only an accepted finding or a request for edits can be appealed.",
        )
    return (
        run,
        finding,
        review.decide(
            session,
            task,
            item_key=f"{index}:appeal",
            decision="appealed",
            suggested={"decision_id": str(current.decision.id)},
            final=None,
            note=reason.strip(),
            user_id=ctx.user.id,
        ),
    )


def decide_appeal(
    session: Session,
    ctx: TenantContext,
    run_id: UUID,
    index: int,
    *,
    decision: AppealDecision,
    note: str,
) -> Decided:
    """Uphold or overturn the first decision. A different reviewer must rule."""
    run, listing, task, finding, current = _finding(session, ctx, run_id, index)
    if not can_review(ctx, listing):
        raise AppError(
            403, "forbidden", "Only an approver other than the listing's agent may review."
        )
    if not note.strip():
        raise AppError(422, "note_required", "Explain the ruling.")
    if current.appeal is None or current.decision is None:
        raise AppError(409, "no_appeal", "This finding has not been appealed.")
    if current.decision.decided_by_user_id == ctx.user.id:
        raise AppError(403, "same_reviewer", "Another reviewer must decide this appeal.")
    return (
        run,
        finding,
        review.decide(
            session,
            task,
            item_key=f"{index}:appeal_decision",
            decision=decision,
            suggested={"appeal_id": str(current.appeal.id)},
            final=None,
            note=note.strip(),
            user_id=ctx.user.id,
        ),
    )


@dataclass
class QueueItem:
    run: AgentRun
    listing: Listing
    index: int
    finding: ComplianceFinding
    review: FindingReview
    waiting_since: datetime


def queue(session: Session, ctx: TenantContext) -> list[QueueItem]:
    """Findings waiting for a reviewer in the organisation, oldest first: undecided ones and
    appeals without a ruling. Only on each listing's newest scan.

    shortcut: loads every open compliance task of the organisation at once; paginate if an
    organisation has thousands open.
    """
    tasks = session.scalars(
        select(ReviewTask).where(
            ReviewTask.organisation_id == ctx.organisation_id,
            ReviewTask.subject_type == REVIEW_SUBJECT,
            ReviewTask.status == "open",
        )
    ).all()
    if not tasks:
        return []
    runs = {
        str(run.id): run
        for run in session.scalars(
            select(AgentRun).where(AgentRun.id.in_([UUID(t.subject_id) for t in tasks]))
        )
    }
    listing_rows = session.scalars(
        select(Listing).where(Listing.id.in_({run.listing_id for run in runs.values()}))
    )
    by_id = {listing.id: listing for listing in listing_rows}
    rows = review.decisions_for(session, [t.id for t in tasks])
    items: list[QueueItem] = []
    for task in tasks:
        run = runs[task.subject_id]
        listing = by_id[run.listing_id]
        if listing.archived_at is not None or not can_review(ctx, listing):
            continue
        findings = findings_of(run)
        for index, item in enumerate(reviews(task, rows, len(findings))):
            if item.state == "open":
                since = run.finished_at or run.created_at
            elif item.state == "appealed" and item.appeal is not None:
                since = item.appeal.decided_at
            else:
                continue
            items.append(QueueItem(run, listing, index, findings[index], item, since))
    return sorted(items, key=lambda i: (i.waiting_since, i.index))
