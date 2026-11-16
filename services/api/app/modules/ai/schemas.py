from collections.abc import Collection
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
