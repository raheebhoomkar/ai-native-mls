"""Neighbourhood facts about a located property. Every value names its source and date.

Only the demo enricher exists: it answers "not available" for everything rather than invent
facts. A real adapter (for example OpenStreetMap Overpass for nearby stations and schools)
implements `Enricher` and is picked in `get_enricher()`.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

ItemKey = Literal["nearest_metro_station", "schools_within_2km", "flood_risk"]
ITEMS: dict[ItemKey, str] = {
    "nearest_metro_station": "Nearest metro station",
    "schools_within_2km": "Schools within 2 km",
    "flood_risk": "Flood risk",
}


@dataclass(frozen=True)
class EnrichmentItem:
    key: ItemKey
    label: str
    value: str | None = None
    source: str | None = None
    retrieved_at: datetime | None = None
    # Why there is no value; set exactly when `value` is None.
    reason: str | None = None


class Enricher(Protocol):
    def enrich(self, latitude: Decimal, longitude: Decimal) -> list[EnrichmentItem]: ...


class DemoEnricher:
    def enrich(self, latitude: Decimal, longitude: Decimal) -> list[EnrichmentItem]:
        return not_available("No neighbourhood data source is set up.")


def not_available(reason: str) -> list[EnrichmentItem]:
    return [EnrichmentItem(key=key, label=label, reason=reason) for key, label in ITEMS.items()]


def get_enricher() -> Enricher:
    return DemoEnricher()
