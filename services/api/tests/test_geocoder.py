import json
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from app.modules.ai.providers import MalformedOutput, ProviderUnavailable, RateLimited
from app.modules.geo import geocoder
from app.modules.geo.geocoder import DemoGeocoder, GeocodeQuery, NominatimGeocoder

QUERY = GeocodeQuery(
    address_line1="12 MG Road", locality="Kothrud", city="Pune", country="IN", postal_code="411038"
)


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(geocoder, "_MIN_INTERVAL", 0.0)


def fake(status: int, payload: object, calls: list[tuple[str, dict[str, str]]] | None = None):  # type: ignore[no-untyped-def]
    def transport(url: str, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
        if calls is not None:
            calls.append((url, headers))
        return status, json.dumps(payload).encode()

    return transport


def test_demo_returns_city_centre_only() -> None:
    result = DemoGeocoder().geocode(
        GeocodeQuery(address_line1="x", city="  New   Delhi", country="in")
    )
    assert result is not None
    assert (result.precision, result.source) == ("city", "demo")
    assert result.latitude == Decimal("28.6139")


def test_demo_knows_seeded_localities() -> None:
    query = GeocodeQuery(address_line1="x", locality="Koregaon  Park", city="Pune", country="IN")
    result = DemoGeocoder().geocode(query)
    assert result is not None
    assert (result.precision, result.latitude) == ("locality", Decimal("18.5362"))


def test_demo_unknown_city_or_country_gives_nothing() -> None:
    assert (
        DemoGeocoder().geocode(GeocodeQuery(address_line1="x", city="Atlantis", country="IN"))
        is None
    )
    assert (
        DemoGeocoder().geocode(GeocodeQuery(address_line1="x", city="Pune", country="US")) is None
    )


def test_nominatim_request_and_result() -> None:
    calls: list[tuple[str, dict[str, str]]] = []
    rows = [{"lat": "18.5074", "lon": "73.8077", "addresstype": "road"}]
    result = NominatimGeocoder(
        "https://nominatim.example/", "test-agent", transport=fake(200, rows, calls)
    ).geocode(QUERY)
    assert result is not None
    assert (result.precision, result.source) == ("address", "nominatim")
    assert result.attribution == "© OpenStreetMap contributors"
    url, headers = calls[0]
    assert url.startswith("https://nominatim.example/search?")
    params = parse_qs(urlparse(url).query)
    assert params["countrycodes"] == ["in"]
    assert params["q"] == ["12 MG Road, Kothrud, Pune, 411038"]
    assert headers["User-Agent"] == "test-agent"


@pytest.mark.parametrize(
    ("kind", "precision"),
    [("house", "address"), ("suburb", "locality"), ("city", "city"), ("", "city")],
)
def test_nominatim_precision(kind: str, precision: str) -> None:
    rows = [{"lat": "1", "lon": "2", "addresstype": kind}]
    result = NominatimGeocoder("https://n", "a", transport=fake(200, rows)).geocode(QUERY)
    assert result is not None and result.precision == precision


def test_nominatim_no_match() -> None:
    assert NominatimGeocoder("https://n", "a", transport=fake(200, [])).geocode(QUERY) is None


@pytest.mark.parametrize(
    ("status", "payload", "error"),
    [
        (429, {}, RateLimited),
        (503, {}, ProviderUnavailable),
        (200, {"not": "a list"}, MalformedOutput),
        (200, [{"lat": "95", "lon": "0"}], MalformedOutput),
    ],
)
def test_nominatim_errors(status: int, payload: object, error: type[Exception]) -> None:
    with pytest.raises(error):
        NominatimGeocoder("https://n", "a", transport=fake(status, payload)).geocode(QUERY)


def test_only_https() -> None:
    with pytest.raises(ValueError, match="https"):
        geocoder.urllib_get("http://n/search", {}, 1)
