from collections.abc import Collection
from datetime import datetime
from typing import Literal, Self, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Observable things only (INSTRUCTIONS.md 2.1): no measurements, room counts or ownership.
Attribute = Literal[
    "room_type",
    "flooring",
    "appliance",
    "window",
    "balcony",
    "condition",
    "furnishing",
    "view",
    "other",
]
ATTRIBUTES: tuple[str, ...] = get_args(Attribute)

# Below this a feature is shown as uncertain, whatever the model says.
UNCERTAIN_BELOW = 0.6


class Feature(BaseModel):
    """One suggestion read from one photo. A suggestion, never a confirmed fact."""

    model_config = ConfigDict(extra="forbid")

    attribute: Attribute
    value: str = Field(min_length=1, max_length=120)
    confidence: float = Field(ge=0, le=1)
    # What in the photo shows it, so a reviewer can check.
    evidence: str = Field(min_length=1, max_length=300)
    uncertain: bool = False

    @model_validator(mode="after")
    def _mark_uncertain(self) -> Self:
        self.uncertain = self.uncertain or self.confidence < UNCERTAIN_BELOW
        return self


class PhotoExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The photo the features came from: the evidence reference.
    media_asset_id: UUID
    features: list[Feature] = Field(max_length=30)


class Extraction(BaseModel):
    """What a vision provider must return. Anything else is malformed output."""

    model_config = ConfigDict(extra="forbid")

    photos: list[PhotoExtraction] = Field(max_length=20)

    def check_inputs(self, sent: Collection[UUID]) -> None:
        """A model may only describe photos it was sent, each once."""
        ids = [photo.media_asset_id for photo in self.photos]
        if len(ids) != len(set(ids)):
            raise ValueError("The output describes the same photo twice.")
        if unknown := set(ids) - set(sent):
            raise ValueError(f"The output describes {len(unknown)} photo(s) that were not sent.")


class DecisionIn(BaseModel):
    """An editor's decision on one suggestion. `value` is required only for `edited`."""

    model_config = ConfigDict(extra="forbid")

    item_key: str = Field(min_length=1, max_length=100)
    decision: Literal["accepted", "edited", "rejected"]
    value: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=500)


class DecisionOut(BaseModel):
    item_key: str
    decision: str
    # The value kept on the listing; null when rejected.
    final_value: str | None
    note: str | None
    decided_by_user_id: UUID
    decided_at: datetime


class AgentRunOut(BaseModel):
    """One AI run as the API shows it. `output` holds suggestions, never confirmed facts."""

    id: UUID
    listing_id: UUID
    status: str
    agent: str
    agent_version: str
    provider: str | None
    model: str | None
    model_version: str | None
    inputs: list[dict[str, str]]
    output: Extraction | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    # Demo output came from no model; the UI must say so.
    is_demo: bool
    # Decisions so far, by item key `<media_asset_id>:<feature index>`.
    decisions: dict[str, DecisionOut]
    # Whether the caller may accept, edit or reject this run's suggestions.
    can_review: bool


# --- Redaction (Module 5) ------------------------------------------------------------------

RedactionCategory = Literal["face", "licence_plate", "phone_number", "watermark", "signage"]
LocatedCategory = Literal["licence_plate", "phone_number", "watermark", "signage"]
LOCATED_CATEGORIES: tuple[str, ...] = get_args(LocatedCategory)


class Region(BaseModel):
    """One area to blur. `box` is left, top, width, height as fractions of the image."""

    model_config = ConfigDict(extra="forbid")

    category: RedactionCategory
    box: tuple[float, float, float, float]
    # None: the detector gives no calibrated score (OpenCV Haar cascades).
    confidence: float | None = Field(default=None, ge=0, le=1)
    detector: str = Field(max_length=50)
    # What it is, never the text itself (a phone number is not copied here).
    note: str | None = Field(default=None, max_length=200)
    uncertain: bool = False

    @model_validator(mode="after")
    def _check(self) -> Self:
        left, top, width, height = self.box
        if not (0 <= left < 1 and 0 <= top < 1 and width > 0 and height > 0):
            raise ValueError("The box must lie inside the image.")
        if left + width > 1.0001 or top + height > 1.0001:
            raise ValueError("The box must lie inside the image.")
        low = self.confidence is not None and self.confidence < UNCERTAIN_BELOW
        self.uncertain = self.uncertain or low
        return self


class LocatedRegion(BaseModel):
    """One region as a vision model reports it (Gemini's own box convention)."""

    model_config = ConfigDict(extra="forbid")

    category: LocatedCategory
    # [ymin, xmin, ymax, xmax], each 0 to 1000.
    box_2d: list[int] = Field(min_length=4, max_length=4)
    confidence: float = Field(ge=0, le=1)
    note: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _check(self) -> Self:
        ymin, xmin, ymax, xmax = self.box_2d
        if not (0 <= ymin < ymax <= 1000 and 0 <= xmin < xmax <= 1000):
            raise ValueError("box_2d must be [ymin, xmin, ymax, xmax] within 0 to 1000.")
        return self

    def to_region(self, detector: str) -> Region:
        ymin, xmin, ymax, xmax = (v / 1000 for v in self.box_2d)
        return Region(
            category=self.category,
            box=(xmin, ymin, xmax - xmin, ymax - ymin),
            confidence=self.confidence,
            detector=detector,
            note=self.note,
        )


class LocatedRegions(BaseModel):
    """What a region locator must return."""

    model_config = ConfigDict(extra="forbid")

    regions: list[LocatedRegion] = Field(max_length=50)


class DetectorUsed(BaseModel):
    detector: str
    version: str
    categories: list[str]


class Unchecked(BaseModel):
    """Categories nobody looked for in this photo, and why."""

    categories: list[str]
    reason: str


class Redaction(BaseModel):
    """What a redaction run found and blurred. Stored on the run; shown to the reviewer."""

    model_config = ConfigDict(extra="forbid")

    policy_version: str
    # Of the image the boxes refer to (upright, as displayed).
    width: int
    height: int
    # Every region here was blurred in the derivative.
    regions: list[Region]
    checked: list[DetectorUsed]
    unchecked: list[Unchecked]
    derivative_id: UUID


class RedactionDecisionIn(BaseModel):
    """Approve (`accepted`) or reject a redacted copy."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted", "rejected"]
    note: str | None = Field(default=None, max_length=500)


class RedactionDecisionOut(BaseModel):
    decision: str
    note: str | None
    decided_by_user_id: UUID
    decided_at: datetime


class RedactionRunOut(BaseModel):
    """One redaction check of one photo."""

    id: UUID
    listing_id: UUID
    # The original photo; it is never changed.
    media_asset_id: UUID
    status: str
    agent_version: str
    provider: str | None
    model: str | None
    model_version: str | None
    output: Redaction | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    # No vision model looked for plates, phone numbers, watermarks or signs.
    is_demo: bool
    # Signed and short-lived, like media URLs. Set once the check has succeeded.
    redacted_url: str | None
    # Null until the check succeeds; then pending until a person decides.
    review_status: Literal["pending", "approved", "rejected"] | None
    decision: RedactionDecisionOut | None
    # Whether the caller may approve or reject.
    can_review: bool
