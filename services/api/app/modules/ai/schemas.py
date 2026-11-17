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
