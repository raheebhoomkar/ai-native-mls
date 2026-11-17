"""Turn an uploaded CSV into validated property and listing payloads, with field-level errors.

No database access here: the caller passes the external IDs already imported.
"""

import csv
import io
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError

from app.modules.imports import fields as f
from app.modules.listings.schemas import ListingCreate, PropertyCreate

MAX_ROWS = 1000
MAX_CHARS = 2_000_000
MAX_EXTERNAL_ID = 100
DEFAULT_CURRENCY = "INR"
DEFAULT_COUNTRY = "IN"
# ListingCreate needs a property ID; the real one replaces this when the property is created.
PENDING_PROPERTY = UUID(int=0)

# Where a canonical field sits in the listing API schemas.
_LOCATIONS: dict[tuple[str | int, ...], str] = {
    ("address", "line1"): "address_line1",
    ("address", "line2"): "address_line2",
    ("address", "locality"): "locality",
    ("address", "city"): "city",
    ("address", "state"): "state",
    ("address", "postal_code"): "postal_code",
    ("address", "country"): "country",
    ("area", "value"): "area",
    ("area", "unit"): "area_unit",
    ("list_price", "amount"): "list_price",
    ("list_price", "currency"): "currency",
}


@dataclass
class Problem:
    # A canonical field name, "file" for the whole file, or "row" for the whole row.
    field: str
    # The source column header, when one column is at fault.
    column: str | None
    message: str


@dataclass
class Column:
    header: str
    field: str | None


@dataclass
class Row:
    # As a spreadsheet shows it: the header is row 1.
    number: int
    # The original non-empty cells of recognised columns, by header. Kept as provenance.
    source: dict[str, str]
    # Normalised values, as text for display.
    values: dict[str, str]
    errors: list[Problem]
    external_id: str | None = None
    property: PropertyCreate | None = None
    listing: ListingCreate | None = None


@dataclass
class ParsedFile:
    columns: list[Column]
    errors: list[Problem]
    rows: list[Row]

    @property
    def ready(self) -> bool:
        return not self.errors and all(not row.errors for row in self.rows)


def _present(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None}


def parse(content: str, already_imported: Collection[str] = ()) -> ParsedFile:
    try:
        records = list(csv.reader(io.StringIO(content.removeprefix("﻿"))))
    except csv.Error as exc:
        return ParsedFile([], [Problem("file", None, f"The file is not valid CSV: {exc}.")], [])
    if not records:
        return ParsedFile([], [Problem("file", None, "The file is empty.")], [])

    header, *body = records
    columns = [Column(h.strip(), f.field_for_header(h) if h.strip() else None) for h in header]
    errors = _column_errors(columns)
    numbered = [(i + 2, cells) for i, cells in enumerate(body) if any(c.strip() for c in cells)]
    if not numbered:
        errors.append(Problem("file", None, "The file has no listing rows under the header."))
    if len(numbered) > MAX_ROWS:
        errors.append(
            Problem(
                "file",
                None,
                f"The file has {len(numbered):,} listing rows; the limit is {MAX_ROWS:,}. "
                "Split it into smaller files.",
            )
        )
    if errors:
        # Without the right columns every row would fail the same way; report the cause once.
        return ParsedFile(columns, errors, [])

    seen: dict[str, int] = {}
    rows = [_row(n, cells, columns, set(already_imported), seen) for n, cells in numbered]
    return ParsedFile(columns, [], rows)


def _column_errors(columns: list[Column]) -> list[Problem]:
    errors: list[Problem] = []
    by_field: dict[str, list[str]] = {}
    for column in columns:
        if column.field:
            by_field.setdefault(column.field, []).append(column.header)
    for name, headers in by_field.items():
        if len(headers) > 1:
            label = f.FIELDS_BY_NAME[name].label
            quoted = " and ".join(f'"{h}"' for h in headers)
            errors.append(Problem(name, None, f"Columns {quoted} are all {label}. Keep only one."))
    for field in f.FIELDS:
        if field.required and field.name not in by_field:
            errors.append(
                Problem(
                    field.name,
                    None,
                    f"No column for {field.label}. Add one with one of these headers: "
                    f"{', '.join(field.accepted_headers)}.",
                )
            )
    return errors


def _row(
    number: int,
    cells: list[str],
    columns: list[Column],
    already_imported: set[str],
    seen: dict[str, int],
) -> Row:
    # field -> (header, cell)
    raw = {
        column.field: (column.header, cell.strip())
        for column, cell in zip(columns, cells, strict=False)
        if column.field and cell.strip()
    }
    # Only recognised columns are kept: an unknown column may hold an owner's phone number.
    row = Row(number, {header: cell for header, cell in raw.values()}, {}, [])
    if any(cell.strip() for cell in cells[len(columns) :]):
        row.errors.append(
            Problem(
                "row",
                None,
                "This row has more cells than the header has columns. "
                "Check for a comma inside a value that is not in quotes.",
            )
        )

    values: dict[str, Any] = {}

    def normalise(name: str, convert: Any, *args: Any) -> Any:
        header, cell = raw[name]
        try:
            return convert(cell, *args)
        except f.FieldValueError as exc:
            row.errors.append(Problem(name, header, str(exc)))
            return None

    for name in f.TEXT_FIELDS:
        if name in raw:
            values[name] = raw[name][1]
    for name, convert in f.SIMPLE_NORMALISERS.items():
        if name in raw:
            values[name] = normalise(name, convert)
    country = values.get("country") or DEFAULT_COUNTRY
    values["country"] = country
    if "postal_code" in raw:
        values["postal_code"] = normalise("postal_code", f.postal_code, country)

    amount = None
    if "list_price" in raw:
        parsed = normalise("list_price", f.price)
        if parsed:
            amount, implied = parsed
            stated = values.get("currency")
            if implied and stated and stated != implied:
                row.errors.append(
                    Problem(
                        "currency",
                        raw["currency"][0],
                        f"The price is in rupees but the currency says {stated}. Make them agree.",
                    )
                )
            values["currency"] = stated or implied or DEFAULT_CURRENCY

    area = None
    if "area" in raw:
        unit_cell = raw["area_unit"][1] if "area_unit" in raw else None
        area = normalise("area", f.area, unit_cell, raw["area"][0])

    external_id = values.get("external_id")
    if external_id:
        if len(external_id) > MAX_EXTERNAL_ID:
            message = f"A Listing ID can be at most {MAX_EXTERNAL_ID} characters."
        elif external_id in already_imported:
            message = (
                f'Listing ID "{external_id}" has already been imported. '
                "Remove this row or change its ID."
            )
        elif external_id in seen:
            message = f'Listing ID "{external_id}" is also on row {seen[external_id]}.'
        else:
            message = ""
            seen[external_id] = number
        if message:
            row.errors.append(Problem("external_id", raw["external_id"][0], message))
    row.external_id = external_id

    property_payload = _present(
        {
            "property_type": values.get("property_type"),
            "address": _present(
                {
                    "line1": values.get("address_line1"),
                    "line2": values.get("address_line2"),
                    "locality": values.get("locality"),
                    "city": values.get("city"),
                    "state": values.get("state"),
                    "postal_code": values.get("postal_code"),
                    "country": country,
                }
            ),
            "bedrooms": values.get("bedrooms"),
            "bathrooms": values.get("bathrooms"),
            "area": {"value": area[0], "unit": area[1]} if area else None,
            "year_built": values.get("year_built"),
        }
    )
    listing_payload = _present(
        {
            "property_id": PENDING_PROPERTY,
            "listing_type": values.get("listing_type"),
            "title": values.get("title"),
            "remarks": values.get("remarks"),
            "list_price": (
                {"amount": amount, "currency": values["currency"]} if amount is not None else None
            ),
            "expires_on": values.get("expires_on"),
        }
    )
    row.property = _validate(PropertyCreate, property_payload, row, raw)
    row.listing = _validate(ListingCreate, listing_payload, row, raw)
    if row.errors:
        row.property = row.listing = None

    if area:
        values["area"] = f"{area[0]} {area[1]}"
        values.pop("area_unit", None)
    if amount is not None:
        values["list_price"] = str(amount)
    row.values = {k: str(v) for k, v in values.items() if v is not None}
    return row


def _validate[M: BaseModel](
    model: type[M], payload: dict[str, Any], row: Row, raw: dict[str, tuple[str, str]]
) -> M | None:
    """Apply the listing API's own rules, so an import never stores what the form refuses."""
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        already = {problem.field for problem in row.errors}
        for error in exc.errors():
            loc = error["loc"]
            name = _LOCATIONS.get(loc[:2], str(loc[0]) if loc else "row")
            if name in already:
                continue  # its normaliser already said what is wrong
            already.add(name)
            label = f.FIELDS_BY_NAME[name].label if name in f.FIELDS_BY_NAME else name
            message = f"{label} is required." if error["type"] == "missing" else f"{error['msg']}."
            row.errors.append(Problem(name, raw[name][0] if name in raw else None, message))
        return None
