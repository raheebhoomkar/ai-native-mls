"""Comparable sales, a baseline estimate and a days-on-market simulation.

Numbers here are estimates, so they are computed in float and rounded to whole units of the
currency; stored listing prices stay exact decimals.
"""

import math
import random
import secrets
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.modules.geo.distance import haversine_km
from app.modules.jobs import service as jobs
from app.modules.jobs.models import Job
from app.modules.listings import service as listings
from app.modules.listings.models import Listing, Property
from app.modules.listings.schemas import ListingFilters, Money
from app.modules.organisations import service as organisations
from app.modules.organisations.deps import TenantContext
from app.modules.outbox import service as outbox
from app.modules.valuation.models import Valuation
from app.modules.valuation.schemas import (
    AskingSummary,
    Comp,
    Estimate,
    EvaluationOut,
    Parameters,
    Simulation,
    ValuationRequest,
    ValuationResult,
)

MODEL_VERSION = "baseline-ppsf-v1"
SIMULATION_VERSION = "dom-lognormal-v1"
MIN_COMPS = 3
MAX_COMPS = 10
MIN_SIMULATION_SAMPLES = 5
SIMULATION_RUNS = 2000
SQFT_PER_SQM = 10.7639
# shortcut: looks at the first 500 filter matches per status; rank in SQL if a city outgrows it.
MAX_CANDIDATES = 500
OFFERS_REASON = "Offers are not recorded in this MLS, so offer outcomes are not simulated."

outbox.subscribe("listing.changed", "valuation.outcome")


def own_listing(session: Session, ctx: TenantContext, listing_id: UUID) -> Listing:
    listing = listings.get_listing(session, ctx, listing_id)  # 404 if not visible
    if listing.organisation_id != ctx.organisation_id:
        raise AppError(404, "not_found", "Listing not found.")
    return listing


def area_sqft(prop: Property) -> float | None:
    if prop.area_value is None:
        return None
    factor = SQFT_PER_SQM if prop.area_unit == "sqm" else 1.0
    return round(float(prop.area_value) * factor, 2)


@dataclass(frozen=True)
class Candidate:
    listing: Listing
    prop: Property
    distance_km: float | None
    area_sqft: float | None


def _candidates(
    session: Session,
    ctx: TenantContext,
    subject: Listing,
    prop: Property,
    params: Parameters,
    status: str,
) -> list[Candidate]:
    """Listings the caller may see that pass every comp rule except the date."""
    located = prop.latitude is not None and prop.longitude is not None
    filters = ListingFilters(
        status=[status],
        property_type=prop.property_type,
        listing_type=subject.listing_type,
        **(
            {
                "near_lat": float(prop.latitude),  # type: ignore[arg-type]
                "near_lon": float(prop.longitude),  # type: ignore[arg-type]
                "radius_km": params.radius_km,
            }
            if located
            else {"city": prop.city, "locality": prop.locality}
        ),
    )
    stmt = listings.filtered_listings(ctx, filters).add_columns(Property).limit(MAX_CANDIDATES)
    subject_area = area_sqft(prop)
    found = []
    for listing, other in session.execute(stmt):
        if listing.id == subject.id or listing.list_price_currency != subject.list_price_currency:
            continue
        other_area = area_sqft(other)
        if subject_area is not None and (
            other_area is None
            or abs(other_area - subject_area) > params.area_tolerance * subject_area
        ):
            continue
        if (
            prop.bedrooms is not None
            and other.bedrooms is not None
            and abs(other.bedrooms - prop.bedrooms) > params.bedrooms_tolerance
        ):
            continue
        distance = (
            round(
                haversine_km(
                    float(prop.latitude),  # type: ignore[arg-type]
                    float(prop.longitude),  # type: ignore[arg-type]
                    float(other.latitude),
                    float(other.longitude),
                ),
                2,
            )
            if located and other.latitude is not None and other.longitude is not None
            else None
        )
        found.append(Candidate(listing, other, distance, other_area))
    return found


def _quartiles(values: list[float]) -> tuple[float, float, float]:
    if len(values) == 1:
        return values[0], values[0], values[0]
    low, median, high = statistics.quantiles(values, n=4, method="inclusive")
    return low, median, high


def _whole(value: float) -> Decimal:
    return Decimal(round(value))


def _money(value: float, currency: str) -> Money:
    """Whole units, written like every other amount (two decimals)."""
    return Money(amount=_whole(value).quantize(Decimal("0.01")), currency=currency)


def simulate_days_on_market(days: list[int], seed: int, runs: int) -> Simulation:
    """Lognormal fitted to observed days on market; reproducible for a seed."""
    base = Simulation(available=False, runs=runs, seed=seed, samples=len(days))
    if len(days) < MIN_SIMULATION_SAMPLES:
        base.reason = (
            f"Needs at least {MIN_SIMULATION_SAMPLES} comparable sales with listed and closed "
            f"dates; found {len(days)}."
        )
        return base
    logs = [math.log(max(day, 1)) for day in days]
    mu, sigma = statistics.fmean(logs), statistics.stdev(logs)
    rng = random.Random(seed)  # noqa: S311  # a simulation, not security
    samples = sorted(rng.lognormvariate(mu, sigma) for _ in range(runs))
    return Simulation(
        available=True,
        runs=runs,
        seed=seed,
        samples=len(days),
        days_p10=round(samples[runs // 10]),
        days_p50=round(samples[runs // 2]),
        days_p90=round(samples[runs * 9 // 10]),
        sold_within={
            str(limit): round(sum(1 for value in samples if value <= limit) / runs, 3)
            for limit in (30, 60, 90)
        },
    )


def _assumptions(prop: Property, params: Parameters, located: bool) -> list[str]:
    where = (
        f"within {params.radius_km:g} km of this property"
        if located
        else f"in {', '.join(p for p in (prop.locality, prop.city) if p)} (this property has "
        "no map point, so distance is not used)"
    )
    return [
        f"Comparable sales: same property type and the same sale or rent, {where}.",
        f"Closed in the last {params.months} months; at most {params.max_comps}, closest first.",
        f"Area within {params.area_tolerance:.0%} of this property's, when it has an area.",
        f"Bedrooms within {params.bedrooms_tolerance} of this property's, when both are known.",
        "Condition is not recorded, so it is not used.",
        "Sale prices are the ones listing agents reported; they are not verified.",
        "Asking prices of active listings are shown separately and are not used in the estimate.",
        f"An estimate needs at least {params.min_comps} comparable sales.",
    ]


def compute(
    session: Session, ctx: TenantContext, subject: Listing, request: ValuationRequest
) -> tuple[Parameters, ValuationResult]:
    params = Parameters(
        **request.model_dump(exclude={"seed"}),
        seed=request.seed if request.seed is not None else secrets.randbelow(2**31),
        min_comps=MIN_COMPS,
        max_comps=MAX_COMPS,
        min_simulation_samples=MIN_SIMULATION_SAMPLES,
        simulation_runs=SIMULATION_RUNS,
    )
    prop = session.get_one(Property, subject.property_id)
    located = prop.latitude is not None and prop.longitude is not None
    subject_area = area_sqft(prop)
    since = datetime.now(UTC) - timedelta(days=round(params.months * 30.44))
    sold = [
        item
        for item in _candidates(session, ctx, subject, prop, params, "sold")
        if item.listing.sold_price_amount is not None
        and item.listing.closed_at is not None
        and item.listing.closed_at >= since
    ]
    sold.sort(
        key=lambda c: (
            c.distance_km or 0.0,
            abs((c.area_sqft or 0) - (subject_area or 0)),
            -c.listing.closed_at.timestamp(),  # type: ignore[union-attr]
        )
    )
    sold = sold[: params.max_comps]
    names = organisations.get_names(session, [c.listing.organisation_id for c in sold])
    currency = subject.list_price_currency

    comps = []
    for item in sold:
        listing = item.listing
        price = float(listing.sold_price_amount)  # type: ignore[arg-type]
        closed: datetime = listing.closed_at  # type: ignore[assignment]  # filtered above
        comps.append(
            Comp(
                listing_id=listing.id,
                title=listing.title,
                organisation_name=names[listing.organisation_id],
                closed_price=Money(amount=listing.sold_price_amount, currency=currency),
                closed_on=closed.date(),
                listed_on=listing.listed_at.date() if listing.listed_at else None,
                days_on_market=(closed - listing.listed_at).days if listing.listed_at else None,
                distance_km=item.distance_km,
                area_sqft=item.area_sqft,
                price_per_sqft=_whole(price / item.area_sqft) if item.area_sqft else None,
                bedrooms=item.prop.bedrooms,
            )
        )

    estimate = None
    reason = None
    if len(comps) < params.min_comps:
        reason = (
            f"Insufficient data: {len(comps)} comparable sale{'s' if len(comps) != 1 else ''} "
            f"found, at least {params.min_comps} needed. No estimate is shown."
        )
    elif subject_area is not None:
        low, mid, high = _quartiles([float(c.price_per_sqft) for c in comps])  # type: ignore[arg-type]
        estimate = Estimate(
            low=_money(low * subject_area, currency),
            median=_money(mid * subject_area, currency),
            high=_money(high * subject_area, currency),
            method="price_per_sqft",
            subject_area_sqft=subject_area,
        )
    else:
        low, mid, high = _quartiles([float(c.closed_price.amount) for c in comps])
        estimate = Estimate(
            low=_money(low, currency),
            median=_money(mid, currency),
            high=_money(high, currency),
            method="closed_price",
            subject_area_sqft=None,
        )

    active = [
        item
        for item in _candidates(session, ctx, subject, prop, params, "active")
        if subject_area is None or item.area_sqft
    ]
    asking = None
    if active:
        values = [
            float(item.listing.list_price_amount) / item.area_sqft
            if subject_area is not None and item.area_sqft
            else float(item.listing.list_price_amount)
            for item in active
        ]
        low, mid, high = _quartiles(values)
        asking = AskingSummary(
            count=len(active),
            basis="price_per_sqft" if subject_area is not None else "price",
            low=_whole(low),
            median=_whole(mid),
            high=_whole(high),
            currency=currency,
        )

    days = [c.days_on_market for c in comps if c.days_on_market is not None]
    result = ValuationResult(
        currency=currency,
        reason=reason,
        estimate=estimate,
        sample_size=len(comps),
        data_from=min((c.closed_on for c in comps), default=None),
        data_to=max((c.closed_on for c in comps), default=None),
        comps=comps,
        asking=asking,
        simulation=simulate_days_on_market(days, params.seed, params.simulation_runs),
        offers_reason=OFFERS_REASON,
        assumptions=_assumptions(prop, params, located),
    )
    return params, result


def request_valuation(
    session: Session, ctx: TenantContext, listing_id: UUID, request: ValuationRequest
) -> Valuation:
    listing = own_listing(session, ctx, listing_id)
    params, result = compute(session, ctx, listing, request)
    estimate = result.estimate
    valuation = Valuation(
        organisation_id=listing.organisation_id,
        listing_id=listing.id,
        requested_by_user_id=ctx.user.id,
        model_version=MODEL_VERSION,
        simulation_version=SIMULATION_VERSION,
        parameters=params.model_dump(mode="json"),
        status="ok" if estimate else "insufficient_data",
        result=result.model_dump(mode="json"),
        estimate_low=estimate.low.amount if estimate else None,
        estimate_median=estimate.median.amount if estimate else None,
        estimate_high=estimate.high.amount if estimate else None,
        # Not the database's now(): that is the transaction start, equal for every row in it.
        created_at=datetime.now(UTC),
    )
    session.add(valuation)
    session.flush()
    session.refresh(valuation)
    return valuation


def list_valuations(session: Session, ctx: TenantContext, listing_id: UUID) -> list[Valuation]:
    listing = own_listing(session, ctx, listing_id)
    return list(
        session.scalars(
            select(Valuation)
            .where(Valuation.listing_id == listing.id)
            .order_by(Valuation.created_at.desc(), Valuation.id)
            .limit(20)
        )
    )


@jobs.handler("valuation.outcome")
def record_outcome(session: Session, job: Job) -> None:
    """Idempotent: fills the sold price into valuations made before the sale, once."""
    if job.payload["subject_type"] != "listing":
        return
    listing = session.get(Listing, UUID(job.payload["subject_id"]))
    if listing is None or listing.status != "sold" or listing.sold_price_amount is None:
        return
    session.execute(
        update(Valuation)
        .where(
            Valuation.listing_id == listing.id,
            Valuation.outcome_price.is_(None),
            Valuation.created_at <= listing.closed_at,
        )
        .values(outcome_price=listing.sold_price_amount, outcome_at=listing.closed_at)
    )


def error_pct(valuation: Valuation) -> float | None:
    if valuation.estimate_median is None or not valuation.outcome_price:
        return None
    return round(
        float((valuation.estimate_median - valuation.outcome_price) / valuation.outcome_price), 4
    )


def within_range(valuation: Valuation) -> bool | None:
    if valuation.estimate_low is None or valuation.estimate_high is None:
        return None
    if valuation.outcome_price is None:
        return None
    return valuation.estimate_low <= valuation.outcome_price <= valuation.estimate_high


def evaluation(session: Session, ctx: TenantContext) -> list[EvaluationOut]:
    rows = session.scalars(
        select(Valuation).where(
            Valuation.organisation_id == ctx.organisation_id,
            Valuation.status == "ok",
            Valuation.outcome_price.is_not(None),
        )
    )
    by_model: dict[str, list[Valuation]] = defaultdict(list)
    for row in rows:
        by_model[row.model_version].append(row)
    return [
        EvaluationOut(
            model_version=model,
            count=len(items),
            median_abs_error_pct=round(
                statistics.median(abs(error_pct(item) or 0.0) for item in items), 4
            ),
            within_range_share=round(
                sum(bool(within_range(item)) for item in items) / len(items), 3
            ),
        )
        for model, items in sorted(by_model.items())
    ]
