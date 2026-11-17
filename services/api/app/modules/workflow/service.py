"""The listing workflow: one LangGraph graph over the existing AI and data steps.

    geocode -> extract -> compliance -> review -> index -> valuation

`review` pauses the run (status `awaiting_review`) while a person still has to decide on the
photo suggestions or the policy findings; the graph stops there until a decision wakes it.

Each pass is one `workflow.advance` job. The graph runs every step that is not finished;
a step either finishes, fails, or says it is waiting for background work (a geocode or an
agent run). While anything waits, the run is queued again a few seconds later.

Steps are idempotent: a finished step is never run again, and a step that started an agent
run keeps its ID and waits on that run instead of starting another.
"""

import itertools
import logging
import operator
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, TypedDict
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.logging import request_id_var
from app.modules.ai import service as extraction
from app.modules.ai.models import AgentRun
from app.modules.auth.models import User
from app.modules.compliance import service as compliance
from app.modules.geo import service as geo
from app.modules.jobs import service as jobs
from app.modules.jobs.models import Job
from app.modules.listings import service as listings
from app.modules.listings.models import Listing, Property
from app.modules.organisations import service as organisations
from app.modules.organisations.deps import TenantContext
from app.modules.outbox import service as outbox
from app.modules.review import service as review
from app.modules.search import service as search
from app.modules.valuation import service as valuation
from app.modules.valuation.schemas import ValuationRequest
from app.modules.workflow.models import WorkflowRun, WorkflowStep

logger = logging.getLogger(__name__)

WORKFLOW = "listing_intake"
WORKFLOW_VERSION = "2"
STEPS: tuple[str, ...] = ("geocode", "extract", "compliance", "review", "index", "valuation")
# A step that raises an unexpected error is tried again on the next pass, this many times.
MAX_STEP_ATTEMPTS = 3
MAX_PASSES = 180  # with POLL, about the 30 minute deadline
DEADLINE = timedelta(minutes=30)
# shortcut: waiting steps are polled, not woken by the work they wait for; wake the run from
# the agent-run handlers if the 10 s delay or the extra jobs start to matter.
POLL = timedelta(seconds=10)
ACTIVE: tuple[str, ...] = ("queued", "running", "waiting", "awaiting_review")
TERMINAL: tuple[str, ...] = ("succeeded", "failed", "cancelled")

StepStatus = Literal["waiting", "succeeded", "failed", "skipped"]


@dataclass
class Outcome:
    status: StepStatus
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class State(TypedDict):
    """Graph state. Each node adds its step's status; the steps' rows hold the details."""

    run_id: str
    statuses: Annotated[dict[str, str], operator.or_]


# --- Steps ---------------------------------------------------------------------------------


@dataclass
class StepContext:
    session: Session
    ctx: TenantContext
    run: WorkflowRun
    step: WorkflowStep
    statuses: dict[str, str]

    @property
    def listing(self) -> Listing:
        return self.session.get_one(Listing, self.run.listing_id)


def _agent_run_outcome(c: StepContext, run_id: str) -> Outcome:
    run = c.session.get_one(AgentRun, UUID(run_id))
    output = {"agent_run_id": run_id, "provider": run.provider, "model": run.model}
    if run.status == "succeeded":
        return Outcome("succeeded", output)
    if run.status == "failed":
        return Outcome("failed", output, run.error or "The agent run failed.")
    job = c.session.get(Job, run.job_id) if run.job_id else None
    if job is not None and job.status == "failed":  # died without updating its run
        return Outcome("failed", output, job.last_error or "The agent run's job failed.")
    return Outcome("waiting", output)


def step_geocode(c: StepContext) -> Outcome:
    prop = c.session.get_one(Property, c.listing.property_id)
    c.session.refresh(prop)
    if prop.geo_status == "located":
        return Outcome(
            "succeeded",
            {"geo_source": prop.geo_source, "geo_precision": prop.geo_precision},
        )
    if prop.geo_status in ("not_found", "failed"):
        return Outcome("skipped", {"reason": prop.geo_error or "The address was not found."})
    if prop.geo_status is None:
        geo.request_geocode(c.session, prop)
    return Outcome("waiting", {"reason": "Looking up the address."})


def step_extract(c: StepContext) -> Outcome:
    if "agent_run_id" not in c.step.output:
        try:
            run = extraction.request_extraction(c.session, c.ctx, c.run.listing_id)
        except AppError as error:
            if error.code == "no_photos":
                return Outcome("skipped", {"reason": error.message})
            raise
        return Outcome("waiting", {"agent_run_id": str(run.id)})
    return _agent_run_outcome(c, c.step.output["agent_run_id"])


def step_compliance(c: StepContext) -> Outcome:
    if "agent_run_id" not in c.step.output:
        _, scans = compliance.list_scans(c.session, c.ctx, c.run.listing_id)
        running = next(
            (
                s
                for s in scans
                if s.status in ("queued", "running") and compliance.stalled(c.session, s) is None
            ),
            None,
        )
        run = running or compliance.request_scan(c.session, c.ctx, c.run.listing_id)[1]
        return Outcome("waiting", {"agent_run_id": str(run.id)})
    return _agent_run_outcome(c, c.step.output["agent_run_id"])


def step_review(c: StepContext) -> Outcome:
    """Pause until people have decided on what the AI steps produced."""
    if any(c.statuses.get(name) in (None, "pending", "waiting") for name in REVIEWED):
        return Outcome("waiting", {"reason": "Waiting for the AI steps.", "awaiting_review": False})
    waiting_on: list[str] = []
    extract = c.session.scalars(
        select(WorkflowStep).where(WorkflowStep.run_id == c.run.id, WorkflowStep.name == "extract")
    ).first()
    run_id = extract.output.get("agent_run_id") if extract else None
    if run_id is not None:
        task = review.get_task_for(c.session, extraction.REVIEW_SUBJECT, run_id)
        if task is not None and task.status == "open":
            waiting_on.append("photo suggestions")
    try:
        compliance.ensure_approvable(c.session, c.run.listing_id)
    except AppError:
        waiting_on.append("policy findings")
    if waiting_on:
        return Outcome(
            "waiting",
            {
                "reason": f"Waiting for a person to review the {' and '.join(waiting_on)}.",
                "awaiting_review": True,
            },
        )
    return Outcome("succeeded", {"reason": None, "awaiting_review": False})


def step_index(c: StepContext) -> Outcome:
    search.index_listing(c.session, c.run.listing_id)
    return Outcome("succeeded", {"indexed": True})


def step_valuation(c: StepContext) -> Outcome:
    # Comps are chosen by distance when the listing has a point, so wait for the geocode.
    if c.statuses.get("geocode") == "waiting":
        return Outcome("waiting", {"reason": "Waiting for the location."})
    # A fixed seed per run, so a pass that is repeated gives the same simulation.
    seed = UUID(str(c.run.id)).int % 2**31
    result = valuation.request_valuation(
        c.session, c.ctx, c.run.listing_id, ValuationRequest(seed=seed)
    )
    return Outcome("succeeded", {"valuation_id": str(result.id), "status": result.status})


# The steps whose output a person reviews.
REVIEWED: tuple[str, ...] = ("extract", "compliance")

STEP_FUNCTIONS: dict[str, Callable[[StepContext], Outcome]] = {
    "geocode": step_geocode,
    "extract": step_extract,
    "compliance": step_compliance,
    "review": step_review,
    "index": step_index,
    "valuation": step_valuation,
}


# --- Graph ---------------------------------------------------------------------------------


def _run_step(
    session: Session,
    ctx: TenantContext,
    run: WorkflowRun,
    step: WorkflowStep,
    statuses: dict[str, str],
) -> str:
    if step.status in ("succeeded", "failed", "skipped"):
        return step.status
    now = datetime.now(UTC)
    step.started_at = step.started_at or now
    try:
        # A savepoint, so a step that breaks half way leaves nothing behind.
        with session.begin_nested():
            outcome = STEP_FUNCTIONS[step.name](StepContext(session, ctx, run, step, statuses))
    except AppError as error:
        outcome = Outcome("failed", {}, error.message)  # a refusal; trying again will not help
    except Exception as error:
        logger.exception("Workflow step failed", extra={"run_id": str(run.id), "step": step.name})
        step.attempts += 1
        step.error = f"{type(error).__name__}: {error}"[:2000]
        if step.attempts >= MAX_STEP_ATTEMPTS:
            step.status = "failed"
            step.finished_at = now
        return step.status
    step.status = outcome.status
    step.output = {**step.output, **outcome.output}
    step.error = outcome.error
    if outcome.status != "waiting":
        step.finished_at = now
    return step.status


def _node(name: str) -> Callable[[State, RunnableConfig], dict[str, Any]]:
    def node(state: State, config: RunnableConfig) -> dict[str, Any]:
        configurable = config["configurable"]
        session: Session = configurable["session"]
        run = session.get_one(WorkflowRun, UUID(state["run_id"]))
        step = session.scalars(
            select(WorkflowStep).where(WorkflowStep.run_id == run.id, WorkflowStep.name == name)
        ).first()
        if step is None:  # a run of an older workflow version, without this step
            return {"statuses": {name: "skipped"}}
        status = _run_step(session, configurable["ctx"], run, step, state["statuses"])
        return {"statuses": {name: status}}

    return node


def _after_review(state: State) -> str:
    """The pause: nothing after `review` runs until the review step has finished."""
    return "go" if state["statuses"].get("review") in ("succeeded", "skipped") else "pause"


def build_graph() -> Any:
    graph = StateGraph(State)
    for name in STEPS:
        graph.add_node(name, _node(name))  # type: ignore[call-overload]
    graph.add_edge(START, STEPS[0])
    for previous, name in itertools.pairwise(STEPS):
        if previous == "review":
            graph.add_conditional_edges("review", _after_review, {"go": name, "pause": END})
        else:
            graph.add_edge(previous, name)
    graph.add_edge(STEPS[-1], END)
    return graph.compile()


GRAPH = build_graph()


# --- Runs ----------------------------------------------------------------------------------


def _own_editable(session: Session, ctx: TenantContext, listing_id: UUID) -> Listing:
    listing = valuation.own_listing(session, ctx, listing_id)  # 404 for other organisations
    if not listings.can_edit(ctx, listing):
        raise AppError(403, "forbidden", "You do not have permission to do this.")
    if listing.archived_at is not None:
        raise AppError(409, "listing_archived", "This listing is archived.")
    return listing


def active_run(session: Session, listing_id: UUID) -> WorkflowRun | None:
    return session.scalars(
        select(WorkflowRun).where(
            WorkflowRun.listing_id == listing_id, WorkflowRun.status.in_(ACTIVE)
        )
    ).first()


def enqueue_pass(session: Session, run: WorkflowRun, delay: timedelta | None = None) -> Job:
    return jobs.enqueue(
        session,
        "workflow.advance",
        {"run_id": str(run.id), "trace_id": run.trace_id},
        organisation_id=run.organisation_id,
        max_attempts=MAX_STEP_ATTEMPTS,
        delay=delay,
    )


def start(session: Session, ctx: TenantContext, listing_id: UUID) -> WorkflowRun:
    """Start the workflow on a listing. Editors of the owning organisation only."""
    listing = _own_editable(session, ctx, listing_id)
    if active_run(session, listing.id) is not None:
        raise AppError(409, "workflow_in_progress", "A workflow is already running here.")
    now = datetime.now(UTC)
    run = WorkflowRun(
        organisation_id=listing.organisation_id,
        listing_id=listing.id,
        requested_by_user_id=ctx.user.id,
        workflow=WORKFLOW,
        workflow_version=WORKFLOW_VERSION,
        status="queued",
        trace_id=request_id_var.get(),
        max_passes=MAX_PASSES,
        deadline=now + DEADLINE,
        created_at=now,
    )
    session.add(run)
    session.flush()
    for position, name in enumerate(STEPS):
        session.add(WorkflowStep(run_id=run.id, name=name, position=position))
    enqueue_pass(session, run)
    session.flush()
    return run


def get_run(session: Session, ctx: TenantContext, run_id: UUID) -> WorkflowRun:
    run = session.get(WorkflowRun, run_id)
    if run is None or run.organisation_id != ctx.organisation_id:
        raise AppError(404, "not_found", "Workflow run not found.")
    listings.get_listing(session, ctx, run.listing_id)  # 404 if no longer visible
    return run


def list_runs(session: Session, ctx: TenantContext, listing_id: UUID) -> Sequence[WorkflowRun]:
    listing = valuation.own_listing(session, ctx, listing_id)
    return session.scalars(
        select(WorkflowRun)
        .where(WorkflowRun.listing_id == listing.id)
        .order_by(WorkflowRun.created_at.desc())
        .limit(20)
    ).all()


def steps_of(session: Session, run: WorkflowRun) -> Sequence[WorkflowStep]:
    return session.scalars(
        select(WorkflowStep).where(WorkflowStep.run_id == run.id).order_by(WorkflowStep.position)
    ).all()


def _finish(session: Session, run: WorkflowRun, status: str, error: str | None = None) -> None:
    run.status = status
    run.error = error
    run.finished_at = datetime.now(UTC)
    outbox.emit(
        session,
        "workflow.finished",
        organisation_id=run.organisation_id,
        subject_type="listing",
        subject_id=run.listing_id,
        payload={"run_id": str(run.id), "status": status},
    )


def _context(session: Session, run: WorkflowRun) -> TenantContext | None:
    """Act as the person who started the run, with the role they have now."""
    for membership, _ in organisations.list_memberships(session, run.requested_by_user_id):
        if membership.organisation_id == run.organisation_id:
            user = session.get_one(User, run.requested_by_user_id)
            return TenantContext(user, run.organisation_id, membership.role)
    return None


def settle(run: WorkflowRun, steps: Sequence[WorkflowStep]) -> str:
    """The run's status from its steps': paused for review, waiting while any can still
    move, then the outcome."""
    if any(s.status == "waiting" and s.output.get("awaiting_review") for s in steps):
        return "awaiting_review"
    statuses = {step.status for step in steps}
    if statuses & {"pending", "waiting"}:
        return "waiting"
    if "failed" in statuses:
        return "failed"
    return "succeeded"


@jobs.handler("workflow.advance")
def advance(session: Session, job: Job) -> None:
    run = session.get(WorkflowRun, UUID(job.payload["run_id"]), with_for_update=True)
    if run is None or run.status not in ("queued", "running", "waiting"):
        return  # finished, cancelled or waiting for a person; nothing to do
    run.passes += 1
    if run.passes > run.max_passes or datetime.now(UTC) > run.deadline:
        waiting = [s.name for s in steps_of(session, run) if s.status in ("pending", "waiting")]
        _finish(
            session,
            run,
            "failed",
            f"The run used up its time or pass budget while waiting on: {', '.join(waiting)}.",
        )
        return
    run.status = "running"
    run.started_at = run.started_at or datetime.now(UTC)
    ctx = _context(session, run)
    if ctx is None:
        _finish(session, run, "failed", "The person who started the run is no longer a member.")
        return

    GRAPH.invoke(
        {"run_id": str(run.id), "statuses": {}},
        {"configurable": {"session": session, "ctx": ctx}},
    )
    steps = steps_of(session, run)
    status = settle(run, steps)
    if status == "awaiting_review":
        run.status = status  # no next pass: a review decision wakes the run (see `wake`)
        return
    if status == "waiting":
        run.status = "waiting"
        enqueue_pass(session, run, POLL)
        return
    failed = [f"{s.name}: {s.error or 'failed'}" for s in steps if s.status == "failed"]
    _finish(session, run, status, "; ".join(failed) or None)


# --- Control: wake, cancel, retry, publication gate ----------------------------------------


def _fresh_budget(run: WorkflowRun) -> None:
    run.passes = 0
    run.deadline = datetime.now(UTC) + DEADLINE


def wake(session: Session, listing_id: UUID) -> None:
    """A review decision was made on the listing: let a paused run check again.

    Called by the routers that record decisions. The run's machine budget starts again,
    since the time a person took to review is not the machine's.
    """
    run = session.scalars(
        select(WorkflowRun)
        .where(WorkflowRun.listing_id == listing_id, WorkflowRun.status == "awaiting_review")
        .with_for_update()
    ).first()
    if run is None:
        return
    run.status = "waiting"
    _fresh_budget(run)
    enqueue_pass(session, run)


def _controllable(session: Session, ctx: TenantContext, run_id: UUID) -> WorkflowRun:
    run = get_run(session, ctx, run_id)
    _own_editable(session, ctx, run.listing_id)
    session.refresh(run, with_for_update=True)
    return run


def cancel(session: Session, ctx: TenantContext, run_id: UUID) -> WorkflowRun:
    """Stop a run. Agent runs it already started carry on; their results stay visible."""
    run = _controllable(session, ctx, run_id)
    if run.status not in ACTIVE:
        raise AppError(409, "workflow_not_active", "Only a run that has not finished can stop.")
    _finish(session, run, "cancelled", f"Cancelled by {ctx.user.email}.")
    return run


def retry(session: Session, ctx: TenantContext, run_id: UUID) -> WorkflowRun:
    """Run a failed or cancelled run again. Finished steps are kept; failed steps start over."""
    run = _controllable(session, ctx, run_id)
    if run.status not in ("failed", "cancelled"):
        raise AppError(409, "workflow_not_retryable", "Only a failed or cancelled run can retry.")
    if active_run(session, run.listing_id) is not None:
        raise AppError(409, "workflow_in_progress", "A workflow is already running here.")
    for step in steps_of(session, run):
        if step.status in ("succeeded", "skipped"):
            continue
        if step.status == "failed":
            step.output = {}  # a failed agent run is not waited on again; a new one starts
        step.status = "pending"
        step.attempts = 0
        step.error = None
        step.finished_at = None
    run.status = "queued"
    run.error = None
    run.finished_at = None
    _fresh_budget(run)
    enqueue_pass(session, run)
    return run


def list_org_runs(
    session: Session, ctx: TenantContext, status: str | None, limit: int = 50
) -> Sequence[WorkflowRun]:
    """The organisation's runs, newest first, for the monitor."""
    query = select(WorkflowRun).where(WorkflowRun.organisation_id == ctx.organisation_id)
    if status == "active":
        query = query.where(WorkflowRun.status.in_(ACTIVE))
    elif status is not None:
        query = query.where(WorkflowRun.status == status)
    return session.scalars(query.order_by(WorkflowRun.created_at.desc()).limit(limit)).all()


def ensure_no_open_run(session: Session, listing_id: UUID) -> None:
    """Publication gate: a listing is not approved while its workflow is still going."""
    run = active_run(session, listing_id)
    if run is not None:
        raise AppError(
            409,
            "workflow_in_progress",
            "The workflow on this listing has not finished"
            + (" and waits for a review" if run.status == "awaiting_review" else "")
            + ". Finish or cancel it before approval.",
        )


listings.APPROVAL_GUARDS.append(ensure_no_open_run)
