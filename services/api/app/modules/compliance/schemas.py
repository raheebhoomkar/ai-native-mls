from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

CheckedField = Literal["title", "remarks"]


class ComplianceFinding(BaseModel):
    """One phrase that may break a policy rule. Decision support for a reviewer, not a verdict."""

    field: CheckedField
    rule_id: str
    rule_title: str
    category: str
    severity: Literal["low", "medium", "high"]
    confidence: float = Field(ge=0, le=1)
    # The exact text of the field that was checked, and where it is in that text.
    evidence: str
    start: int
    end: int
    explanation: str
    suggestion: str
    # "rule": a pattern of the policy matched. "model": the language model reported it.
    source: Literal["rule", "model"]


class ComplianceScan(BaseModel):
    """What a scan found. Stored on the run; the policy is copied so the record stands alone."""

    model_config = ConfigDict(extra="forbid")

    policy_id: str
    policy_version: str
    policy_name: str
    policy_notice: str
    jurisdiction: str
    findings: list[ComplianceFinding]
    # The rule check always runs. The model check may not, and then this says why.
    model_checked: bool
    model_note: str | None
    # Model findings dropped because their quote was not in the text or the rule was unknown.
    model_dropped: int = 0


class ModelFinding(BaseModel):
    """What the language model returns for one phrase. Checked against the text before use."""

    model_config = ConfigDict(extra="forbid")

    field: CheckedField
    rule_id: str = Field(max_length=20)
    evidence: str = Field(min_length=1, max_length=300)
    confidence: float = Field(ge=0, le=1)
    explanation: str = Field(min_length=1, max_length=500)
    suggestion: str = Field(min_length=1, max_length=500)


class ModelReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[ModelFinding] = Field(max_length=30)


class ComplianceDecisionOut(BaseModel):
    decision: str
    note: str | None
    decided_by_user_id: UUID
    decided_by_name: str
    decided_at: datetime


ReviewState = Literal[
    "open", "accepted", "dismissed", "edits_requested", "appealed", "upheld", "overturned"
]


class FindingReviewOut(BaseModel):
    """The review trail of one finding: decision, appeal, ruling on the appeal."""

    state: ReviewState
    decision: ComplianceDecisionOut | None
    appeal: ComplianceDecisionOut | None
    appeal_decision: ComplianceDecisionOut | None


class FindingDecisionIn(BaseModel):
    """accepted: a real problem the agent should fix. dismissed: not a problem.
    edits_requested: the reviewer wants a rewrite; say what in the note.
    """

    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted", "dismissed", "edits_requested"]
    note: str | None = Field(default=None, max_length=1000)


class AppealIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)


class AppealDecisionIn(BaseModel):
    """upheld: the first decision stands. overturned: the finding is set aside."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["upheld", "overturned"]
    note: str = Field(min_length=1, max_length=1000)


class ComplianceQueueItemOut(BaseModel):
    """A finding waiting for a reviewer: undecided, or appealed without a ruling."""

    scan_id: UUID
    listing_id: UUID
    listing_title: str
    finding_index: int
    finding: ComplianceFinding
    state: Literal["open", "appealed"]
    review: FindingReviewOut
    policy_version: str
    waiting_since: datetime


class ComplianceScanOut(BaseModel):
    """One policy check of a listing's title and remarks."""

    id: UUID
    listing_id: UUID
    status: str
    # The listing version whose text was checked.
    listing_version: int
    # The title and remarks as they were checked; finding offsets point into these.
    checked_title: str
    checked_remarks: str
    provider: str | None
    model: str | None
    model_version: str | None
    output: ComplianceScan | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    # No language model looked at the text; only the rule check ran.
    is_demo: bool
    # One per finding, in the same order as output.findings.
    reviews: list[FindingReviewOut]
    # False once a newer scan replaced this one; then nothing more can be decided on it.
    review_open: bool
    can_review: bool
    can_appeal: bool
