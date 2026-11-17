from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.listings.schemas import Money

DISCLAIMER = (
    "Not an appraisal and not a guaranteed sale price. Decision support from sales reported "
    "by listing agents, which are not verified."
)
PRICE_SOURCE = "Reported by the listing agent when marking the listing sold; not verified."


class ValuationRequest(BaseModel):
    """Every assumption; all are stored with the result."""

    seed: Annotated[int, Field(ge=0, lt=2**31)] | None = Field(
        default=None, description="Simulation seed. Same seed and comps give the same answer."
    )
    radius_km: Annotated[float, Field(ge=0.5, le=50)] = 5
    months: Annotated[int, Field(ge=3, le=60, description="Sales closed in this window.")] = 24
    area_tolerance: Annotated[float, Field(ge=0.05, le=0.5)] = 0.3
    bedrooms_tolerance: Annotated[int, Field(ge=0, le=3)] = 1


class Parameters(ValuationRequest):
    seed: int  # always set once stored
    min_comps: int
    max_comps: int
    min_simulation_samples: int
    simulation_runs: int


class Comp(BaseModel):
    listing_id: UUID
    title: str
    organisation_name: str
    closed_price: Money
    closed_on: date
    listed_on: date | None
    days_on_market: int | None
    distance_km: float | None = Field(description="Null when either point is unknown.")
    area_sqft: float | None
    price_per_sqft: Decimal | None
    bedrooms: int | None
    price_source: str = PRICE_SOURCE


class Estimate(BaseModel):
    low: Money
    median: Money
    high: Money
    method: Literal["price_per_sqft", "closed_price"] = Field(
        description="price_per_sqft: comps' price per sqft times the subject's area. "
        "closed_price: comps' prices, used when the subject has no area."
    )
    subject_area_sqft: float | None


class AskingSummary(BaseModel):
    """Active listings matching the same rules. Asking prices, not sale prices; never in the
    estimate."""

    count: int
    basis: Literal["price_per_sqft", "price"]
    low: Decimal
    median: Decimal
    high: Decimal
    currency: str


class Simulation(BaseModel):
    available: bool
    reason: str | None = None
    runs: int
    seed: int
    samples: int = Field(description="Comps with both a listed and a closed date.")
    days_p10: int | None = None
    days_p50: int | None = None
    days_p90: int | None = None
    sold_within: dict[str, float] = Field(
        default_factory=dict, description="Share of simulated runs sold within 30, 60, 90 days."
    )


class ValuationResult(BaseModel):
    currency: str = Field(description="The listing's currency; every amount here is in it.")
    reason: str | None = Field(description="Why there is no estimate. Set exactly when it is null.")
    estimate: Estimate | None
    sample_size: int
    data_from: date | None = Field(description="Oldest comp's closing date.")
    data_to: date | None = Field(description="Newest comp's closing date.")
    comps: list[Comp]
    asking: AskingSummary | None
    simulation: Simulation
    offers_reason: str = Field(description="Why offer outcomes are not simulated.")
    assumptions: list[str]


class Outcome(BaseModel):
    price: Money
    at: datetime
    error_pct: float | None = Field(description="(estimate median - sold price) / sold price.")
    within_range: bool | None


class ValuationOut(BaseModel):
    id: UUID
    listing_id: UUID
    status: Literal["ok", "insufficient_data"]
    model_version: str
    simulation_version: str
    parameters: Parameters
    result: ValuationResult
    outcome: Outcome | None
    requested_by_user_id: UUID
    created_at: datetime
    disclaimer: str = DISCLAIMER


class EvaluationOut(BaseModel):
    model_version: str
    count: int = Field(description="Valuations of listings that later sold.")
    median_abs_error_pct: float | None
    within_range_share: float | None
