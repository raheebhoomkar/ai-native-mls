"""Geocoders: one interface, an OpenStreetMap Nominatim adapter and a labelled demo one."""

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Protocol

from app.core.config import get_settings
from app.modules.ai.providers import (
    MalformedOutput,
    ProviderRejected,
    ProviderTimeout,
    ProviderUnavailable,
    RateLimited,
)

Precision = Literal["address", "locality", "city"]
OSM_ATTRIBUTION = "© OpenStreetMap contributors"


@dataclass(frozen=True)
class GeocodeQuery:
    address_line1: str
    city: str
    country: str
    locality: str | None = None
    state: str | None = None
    postal_code: str | None = None


@dataclass(frozen=True)
class GeocodeResult:
    latitude: Decimal
    longitude: Decimal
    precision: Precision
    source: str
    retrieved_at: datetime
    attribution: str | None = None


class Geocoder(Protocol):
    def geocode(self, query: GeocodeQuery) -> GeocodeResult | None: ...


# Approximate city centres (public, rounded to ~1 km). The demo never claims more than "city".
_CITY_CENTRES: dict[str, tuple[str, str]] = {
    "mumbai": ("19.0760", "72.8777"),
    "pune": ("18.5204", "73.8567"),
    "delhi": ("28.6139", "77.2090"),
    "new delhi": ("28.6139", "77.2090"),
    "bengaluru": ("12.9716", "77.5946"),
    "bangalore": ("12.9716", "77.5946"),
    "hyderabad": ("17.3850", "78.4867"),
    "chennai": ("13.0827", "80.2707"),
    "kolkata": ("22.5726", "88.3639"),
    "ahmedabad": ("23.0225", "72.5714"),
    "thane": ("19.2183", "72.9781"),
    "navi mumbai": ("19.0330", "73.0297"),
    "gurugram": ("28.4595", "77.0266"),
    "noida": ("28.5355", "77.3910"),
}

# Approximate centres of the localities the seed uses, so demo listings do not share one point.
_LOCALITY_CENTRES: dict[tuple[str, str], tuple[str, str]] = {
    ("powai", "mumbai"): ("19.1176", "72.9060"),
    ("andheri west", "mumbai"): ("19.1364", "72.8296"),
    ("worli", "mumbai"): ("19.0176", "72.8180"),
    ("koregaon park", "pune"): ("18.5362", "73.8940"),
    ("baner", "pune"): ("18.5590", "73.7868"),
}


def _key(text: str | None) -> str:
    return " ".join((text or "").lower().split())


class DemoGeocoder:
    """Labelled demo: the centre of a known locality or city, never a street-level point."""

    def geocode(self, query: GeocodeQuery) -> GeocodeResult | None:
        if query.country.upper() != "IN":
            return None
        city = _key(query.city)
        precision: Precision = "locality"
        centre = _LOCALITY_CENTRES.get((_key(query.locality), city))
        if centre is None:
            precision, centre = "city", _CITY_CENTRES.get(city)
        if centre is None:
            return None
        return GeocodeResult(
            latitude=Decimal(centre[0]),
            longitude=Decimal(centre[1]),
            precision=precision,
            source="demo",
            retrieved_at=datetime.now(UTC),
        )


GetTransport = Callable[[str, dict[str, str], float], tuple[int, bytes]]


def urllib_get(url: str, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
    if not url.startswith("https://"):
        raise ValueError("Only https URLs are allowed.")
    request = urllib.request.Request(url, headers=headers, method="GET")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310  # https checked above
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


# Nominatim allows at most 1 request per second per application.
_MIN_INTERVAL = 1.0
_lock = threading.Lock()
_last_call = 0.0

# Nominatim's addresstype values, mapped to how much the point can be trusted.
_ADDRESS_TYPES = {"house", "building", "road", "street"}
_LOCALITY_TYPES = {"suburb", "neighbourhood", "quarter", "locality", "postcode", "village"}


class NominatimGeocoder:
    def __init__(
        self,
        base_url: str,
        user_agent: str,
        timeout: float = 10,
        transport: GetTransport = urllib_get,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent
        self._timeout = timeout
        self._transport = transport

    def geocode(self, query: GeocodeQuery) -> GeocodeResult | None:
        params = {
            "format": "jsonv2",
            "limit": "1",
            "addressdetails": "0",
            "countrycodes": query.country.lower(),
            "q": ", ".join(
                part
                for part in (
                    query.address_line1,
                    query.locality,
                    query.city,
                    query.state,
                    query.postal_code,
                )
                if part
            ),
        }
        url = f"{self._base_url}/search?{urllib.parse.urlencode(params)}"
        headers = {"User-Agent": self._user_agent, "Accept": "application/json"}
        status, body = self._call(url, headers)
        if status == 429:
            raise RateLimited("Nominatim rate limit reached.", retry_after=60)
        if status in (401, 403):
            raise ProviderRejected(f"Nominatim refused the request ({status}).")
        if status >= 400:
            raise ProviderUnavailable(f"Nominatim answered {status}.")
        try:
            rows = json.loads(body)
            if not rows:
                return None
            row = rows[0]
            latitude, longitude = Decimal(row["lat"]), Decimal(row["lon"])
        except (ValueError, KeyError, TypeError, IndexError) as error:
            raise MalformedOutput("Nominatim answer could not be read.") from error
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise MalformedOutput("Nominatim returned a point out of range.")
        kind = row.get("addresstype") or row.get("type") or ""
        precision: Precision = (
            "address"
            if kind in _ADDRESS_TYPES
            else "locality"
            if kind in _LOCALITY_TYPES
            else "city"
        )
        return GeocodeResult(
            latitude=latitude.quantize(Decimal("0.0000001")),
            longitude=longitude.quantize(Decimal("0.0000001")),
            precision=precision,
            source="nominatim",
            retrieved_at=datetime.now(UTC),
            attribution=OSM_ATTRIBUTION,
        )

    def _call(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        global _last_call
        # shortcut: 1 request/s is enforced per process; with several workers, share a limiter.
        with _lock:
            wait = _last_call + _MIN_INTERVAL - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                return self._transport(url, headers, self._timeout)
            except TimeoutError as error:
                raise ProviderTimeout("Nominatim did not answer in time.") from error
            except OSError as error:
                raise ProviderUnavailable("Nominatim could not be reached.") from error
            finally:
                _last_call = time.monotonic()


def get_geocoder() -> Geocoder:
    settings = get_settings()
    if settings.geocoder == "nominatim":
        return NominatimGeocoder(settings.nominatim_url, settings.geocoder_user_agent)
    return DemoGeocoder()
