"""Great-circle distance, in Python and in SQL (the same haversine formula)."""

from math import asin, cos, radians, sin, sqrt
from typing import Any

from sqlalchemy import ColumnElement, and_, func

EARTH_RADIUS_KM = 6371.0
KM_PER_DEGREE_LATITUDE = 111.32


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    a = (
        sin(radians(lat2 - lat1) / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * asin(sqrt(min(a, 1.0)))


def within_km(
    latitude: Any, longitude: Any, lat: float, lon: float, radius_km: float
) -> ColumnElement[bool]:
    """Rows whose point lies within `radius_km` of (lat, lon).

    A bounding box first, so the (organisation, latitude, longitude) index can help, then the
    exact distance. shortcut: a box that crosses the 180th meridian finds nothing there; fine
    for India, fix before serving the Pacific.
    """
    dlat = radius_km / KM_PER_DEGREE_LATITUDE
    dlon = radius_km / (KM_PER_DEGREE_LATITUDE * max(cos(radians(lat)), 0.01))
    lat1, lat2 = func.radians(lat), func.radians(latitude)
    a = func.power(func.sin((lat2 - lat1) / 2), 2) + func.cos(lat1) * func.cos(lat2) * func.power(
        func.sin((func.radians(longitude) - func.radians(lon)) / 2), 2
    )
    distance = 2 * EARTH_RADIUS_KM * func.asin(func.sqrt(func.least(a, 1.0)))
    return and_(
        latitude.between(lat - dlat, lat + dlat),
        longitude.between(lon - dlon, lon + dlon),
        distance <= radius_km,
    )
