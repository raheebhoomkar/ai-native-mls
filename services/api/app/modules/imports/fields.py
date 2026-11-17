"""Canonical listing fields for import, and the variants external files use for them.

The canonical fields are the ones the listing and property API already accepts. Each names
the closest RESO Data Dictionary field where one exists. This is alignment only: no RESO
version is targeted and no conformance is claimed (INSTRUCTIONS.md §2.2, §14 question 3).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any


class FieldValueError(ValueError):
    """A cell value that cannot be normalised. The message tells the user how to fix it."""


@dataclass(frozen=True)
class CanonicalField:
    name: str
    label: str
    reso_name: str | None
    required: bool
    # Other headers external files use for this field, as people write them.
    variants: tuple[str, ...]
    # Accepted value formats, shown to users.
    help: str

    @property
    def accepted_headers(self) -> list[str]:
        names = [self.label, *([self.reso_name] if self.reso_name else []), *self.variants]
        return list(dict.fromkeys(names))


FIELDS: tuple[CanonicalField, ...] = (
    CanonicalField(
        "external_id", "Listing ID", "ListingId", False,
        ("MLS number", "MLS no", "MLS", "Reference", "Reference no", "Ref", "Ref no"),
        "Your own ID for the listing. Used to stop the same listing being imported twice.",
    ),
    CanonicalField(
        "listing_type", "Listing type", None, True,
        ("Transaction type", "Sale or rent", "Sale/Rent", "Purpose", "Listing for"),
        "sale or rent. Also accepted: sell, resale, for sale, lease, rental, for rent.",
    ),
    CanonicalField(
        "property_type", "Property type", "PropertyType", True,
        ("Property subtype", "PropertySubType", "Type of property", "Category"),
        "apartment, house, villa, plot, commercial or other. "
        "Also accepted: flat, condominium, independent house, bungalow, land, office, shop.",
    ),
    CanonicalField(
        "title", "Title", None, True,
        ("Headline", "Listing title", "Name"),
        "Up to 200 characters.",
    ),
    CanonicalField(
        "remarks", "Remarks", "PublicRemarks", False,
        ("Description", "Property description", "Details"),
        "Up to 10,000 characters.",
    ),
    CanonicalField(
        "list_price", "Price", "ListPrice", True,
        ("List price", "Asking price", "Expected price", "Price (INR)", "Price (Rs)", "Rent",
         "Monthly rent"),
        "A number such as 4500000, ₹45,00,000, 45 lakh or 1.25 crore.",
    ),
    CanonicalField(
        "currency", "Currency", None, False,
        ("Currency code",),
        "Three-letter code such as INR. Empty means INR.",
    ),
    CanonicalField(
        "address_line1", "Address", "UnparsedAddress", True,
        ("Address line 1", "Street address", "Street", "Address 1"),
        "Up to 200 characters.",
    ),
    CanonicalField(
        "address_line2", "Address line 2", None, False,
        ("Address 2", "Line 2"),
        "Up to 200 characters.",
    ),
    CanonicalField(
        "locality", "Locality", None, False,
        ("Neighbourhood", "Neighborhood", "Suburb", "Area name"),
        "Up to 100 characters.",
    ),
    CanonicalField("city", "City", "City", True, ("Town",), "Up to 100 characters."),
    CanonicalField(
        "state", "State", "StateOrProvince", False, ("Province",), "Up to 100 characters."
    ),
    CanonicalField(
        "postal_code", "PIN code", "PostalCode", False,
        ("Pincode", "PIN", "Postal code", "Postcode", "ZIP", "ZIP code"),
        "Six digits for India.",
    ),
    CanonicalField(
        "country", "Country", "Country", False,
        ("Country code",),
        "Two-letter code such as IN, or India. Empty means IN.",
    ),
    CanonicalField(
        "bedrooms", "Bedrooms", "BedroomsTotal", False,
        ("Beds", "BHK", "No of bedrooms", "Number of bedrooms"),
        "A whole number such as 3, or 3 BHK.",
    ),
    CanonicalField(
        "bathrooms", "Bathrooms", "BathroomsTotalInteger", False,
        ("Baths", "No of bathrooms", "Number of bathrooms"),
        "A whole number.",
    ),
    CanonicalField(
        "area", "Area", "LivingArea", False,
        ("Carpet area", "Living area", "Size"),
        "A number with its unit, such as 1,250 sq ft, 116 sqm or 140 sq yd (converted to sq ft), "
        "or the unit in the Area unit column or in the header, as in 'Area (sq ft)'. "
        "Built-up and super built-up area are not the living area and are not imported.",
    ),
    CanonicalField(
        "area_unit", "Area unit", "LivingAreaUnits", False,
        ("Unit of area", "Area units"),
        "sq ft, sqm or sq yd.",
    ),
    CanonicalField(
        "year_built", "Year built", "YearBuilt", False,
        ("Construction year", "Year of construction", "Built in"),
        "Four digits, such as 2015.",
    ),
    CanonicalField(
        "expires_on", "Expiry date", "ExpirationDate", False,
        ("Expiry", "Expires on", "Listing expiry", "Expiration date"),
        "YYYY-MM-DD or DD/MM/YYYY.",
    ),
)  # fmt: skip

FIELDS_BY_NAME = {field.name: field for field in FIELDS}


def key(text: str) -> str:
    """Comparison form of a header or value: lower-case letters and digits only."""
    return re.sub(r"[^a-z0-9²]", "", text.lower())


_UNITS: dict[str, str] = {
    **dict.fromkeys(
        ("sqft", "sqfeet", "sqfoot", "squarefeet", "squarefoot", "sft", "ft2", "ft²"), "sqft"
    ),
    **dict.fromkeys(
        ("sqm", "sqmt", "sqmtr", "sqmeter", "sqmeters", "sqmetre", "sqmetres", "squaremeter",
         "squaremeters", "squaremetre", "squaremetres", "m2", "m²"),
        "sqm",
    ),
    **dict.fromkeys(
        ("sqyd", "sqyard", "sqyards", "squareyard", "squareyards", "yd2", "gaj"), "sqyd"
    ),
}  # fmt: skip
# Longest first, so "sqmtr" is found before "sqm" when stripping a header suffix.
_UNIT_KEYS = sorted(_UNITS, key=len, reverse=True)


def _build_header_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for field in FIELDS:
        for header in (field.name, *field.accepted_headers):
            existing = index.setdefault(key(header), field.name)
            if existing != field.name:
                raise RuntimeError(f"{header!r} maps to {existing} and {field.name}")
    return index


_HEADERS = _build_header_index()


def split_unit_suffix(header_key: str) -> tuple[str, str | None]:
    """'areasqft' -> ('area', 'sqft'). The unit is None when the key has no unit suffix."""
    for unit_key in _UNIT_KEYS:
        if header_key.endswith(unit_key) and len(header_key) > len(unit_key):
            return header_key[: -len(unit_key)], _UNITS[unit_key]
    return header_key, None


def field_for_header(header: str) -> str | None:
    """The canonical field a source column holds, or None when it is not recognised."""
    header_key = key(header)
    if header_key in _HEADERS:
        return _HEADERS[header_key]
    base, unit = split_unit_suffix(header_key)
    # Only area columns carry a unit in their header ("Carpet area (sq ft)").
    if unit is not None and _HEADERS.get(base) == "area":
        return "area"
    return None


# --- Value normalisers --------------------------------------------------------------------
# Each takes a non-empty, stripped cell and returns the canonical value or raises
# FieldValueError with a message that says how to fix the cell.


def _quote(raw: str) -> str:
    return f'"{raw}"' if len(raw) <= 40 else f'"{raw[:40]}…"'


def _lookup(table: dict[str, tuple[str, ...]], raw: str, error: str) -> str:
    raw_key = key(raw)
    for value, synonyms in table.items():
        if raw_key == value or raw_key in synonyms:
            return value
    raise FieldValueError(f"{_quote(raw)} {error}")


_LISTING_TYPES = {
    "sale": ("sell", "forsale", "resale", "outright", "buy"),
    "rent": ("rental", "lease", "forrent", "forlease", "letting", "residentiallease"),
}

_PROPERTY_TYPES = {
    "apartment": ("flat", "condo", "condominium", "studio", "studioapartment", "penthouse",
                  "builderfloor", "serviceapartment", "residentialapartment"),
    "house": ("independenthouse", "singlefamilyresidence", "singlefamily", "townhouse",
              "rowhouse", "bungalow", "duplex", "residentialhouse"),
    "villa": ("independentvilla",),
    "plot": ("land", "lot", "residentialplot", "residentialland"),
    "commercial": ("office", "officespace", "shop", "showroom", "retail", "warehouse",
                   "commercialoffice", "commercialshop"),
    "other": (),
}  # fmt: skip


def listing_type(raw: str) -> str:
    return _lookup(_LISTING_TYPES, raw, "is not a listing type. Use sale or rent.")


def property_type(raw: str) -> str:
    return _lookup(
        _PROPERTY_TYPES,
        raw,
        "is not a known property type. Use apartment, house, villa, plot, commercial or other.",
    )


_RUPEE_PREFIX = re.compile(r"^(?:₹|rs\.?|inr)\s*", re.IGNORECASE)
_RUPEE_SUFFIX = re.compile(r"\s*(?:₹|inr|rupees|rs\.?)$", re.IGNORECASE)
_PRICE = re.compile(
    r"^(?P<number>\d+(?:\.\d+)?)\s*(?P<scale>lakhs?|lacs?|l|crores?|cr|k)?$", re.IGNORECASE
)
_SCALES = {"l": 100_000, "lac": 100_000, "lakh": 100_000, "cr": 10_000_000, "crore": 10_000_000,
           "k": 1_000}  # fmt: skip


def price(raw: str) -> tuple[Decimal, str | None]:
    """The amount, and "INR" when the cell itself says rupees."""
    text, prefix_count = _RUPEE_PREFIX.subn("", raw.strip())
    text, suffix_count = _RUPEE_SUFFIX.subn("", text)
    match = _PRICE.match(text.replace(",", "").strip())
    if not match:
        raise FieldValueError(
            f"{_quote(raw)} is not a price. "
            "Use a number such as 4500000, ₹45,00,000, 45 lakh or 1.25 crore."
        )
    amount = Decimal(match["number"])
    if match["scale"]:
        amount *= _SCALES[match["scale"].lower().rstrip("s")]
    return amount, "INR" if prefix_count or suffix_count else None


def currency(raw: str) -> str:
    if raw.strip() == "₹" or key(raw) in ("rs", "rupee", "rupees"):
        return "INR"
    if not re.fullmatch(r"[A-Za-z]{3}", raw):
        raise FieldValueError(f"{_quote(raw)} is not a currency code. Use a code such as INR.")
    return raw.upper()


def area_unit(raw: str) -> str:
    unit = _UNITS.get(key(raw))
    if unit is None:
        raise FieldValueError(f"{_quote(raw)} is not an area unit. Use sq ft, sqm or sq yd.")
    return unit


_AREA = re.compile(r"^(?P<number>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>.*)$")
_SQFT_PER_SQYD = 9  # exact: one yard is three feet


def area(raw: str, unit_cell: str | None, header: str) -> tuple[Decimal, str]:
    """The area in sq ft or sqm. The unit comes from the cell, else the unit column, else the
    header; square yards are converted exactly to square feet."""
    match = _AREA.match(raw.strip())
    if not match:
        raise FieldValueError(f"{_quote(raw)} is not an area. Use a number such as 1,250 sq ft.")
    value = Decimal(match["number"].replace(",", ""))
    in_cell = area_unit(match["unit"]) if match["unit"] else None
    in_column = area_unit(unit_cell) if unit_cell else None
    if in_cell and in_column and in_cell != in_column:
        raise FieldValueError(
            f"{_quote(raw)} is in {in_cell} but the Area unit column says {in_column}. "
            "Make them agree."
        )
    unit = in_cell or in_column or split_unit_suffix(key(header))[1]
    if unit is None:
        raise FieldValueError(
            f"{_quote(raw)} has no unit. Write it as 1,250 sq ft or 116 sqm, "
            "or add an Area unit column."
        )
    if unit == "sqyd":
        return value * _SQFT_PER_SQYD, "sqft"
    return value, unit


def _whole_number(raw: str, suffixes: str, what: str) -> int:
    match = re.fullmatch(rf"(\d+)\s*(?:{suffixes})?", raw.strip(), re.IGNORECASE)
    if not match:
        raise FieldValueError(f"{_quote(raw)} is not a number of {what}. Use a whole number.")
    return int(match[1])


def bedrooms(raw: str) -> int:
    return _whole_number(raw, r"bhk|beds?|bedrooms?", "bedrooms")


def bathrooms(raw: str) -> int:
    return _whole_number(raw, r"baths?|bathrooms?", "bathrooms")


def year_built(raw: str) -> int:
    if not re.fullmatch(r"\d{4}", raw.strip()):
        raise FieldValueError(f"{_quote(raw)} is not a year. Use four digits, such as 2015.")
    return int(raw)


def expiry_date(raw: str) -> date:
    text = raw.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return date.fromisoformat(text)
        # India writes day first: 03/04/2027 is 3 April.
        match = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", text)
        if match:
            return date(int(match[3]), int(match[2]), int(match[1]))
    except ValueError:
        raise FieldValueError(f"{_quote(raw)} is not a real date.") from None
    raise FieldValueError(f"{_quote(raw)} is not a date. Use YYYY-MM-DD or DD/MM/YYYY.")


_COUNTRY_NAMES = {"india": "IN", "bharat": "IN", "ind": "IN"}


def country(raw: str) -> str:
    raw_key = key(raw)
    if raw_key in _COUNTRY_NAMES:
        return _COUNTRY_NAMES[raw_key]
    if not re.fullmatch(r"[A-Za-z]{2}", raw.strip()):
        raise FieldValueError(f"{_quote(raw)} is not a country code. Use two letters, such as IN.")
    return raw.strip().upper()


def postal_code(raw: str, country_code: str) -> str:
    code = raw.strip()
    if country_code == "IN":
        code = code.replace(" ", "")
        if not re.fullmatch(r"\d{6}", code):
            raise FieldValueError(f"{_quote(raw)} is not a PIN code. A PIN code has six digits.")
    return code


# Fields whose value is plain text; anything else has a normaliser above or is combined.
TEXT_FIELDS = ("external_id", "title", "remarks", "address_line1", "address_line2", "locality",
               "city", "state")  # fmt: skip

SIMPLE_NORMALISERS: dict[str, Callable[[str], Any]] = {
    "listing_type": listing_type,
    "property_type": property_type,
    "currency": currency,
    "bedrooms": bedrooms,
    "bathrooms": bathrooms,
    "year_built": year_built,
    "expires_on": expiry_date,
    "country": country,
}
