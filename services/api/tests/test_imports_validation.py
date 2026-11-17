"""Import mapping and validation, without a database."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.imports import fields as f
from app.modules.imports.validation import MAX_ROWS, parse

FIXTURES = Path(__file__).parent / "fixtures" / "imports"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _errors(row_errors: list) -> dict[str, str]:  # type: ignore[type-arg]
    return {problem.field: problem.message for problem in row_errors}


def test_reso_named_file_maps_to_canonical_fields() -> None:
    parsed = parse(_read("reso.csv"))
    assert parsed.ready, (parsed.errors, [r.errors for r in parsed.rows])
    assert all(column.field for column in parsed.columns)
    first, second = parsed.rows
    assert first.number == 2 and first.external_id == "RESO-1"
    assert first.property and first.listing
    assert first.property.property_type == "apartment"
    assert first.property.area and first.property.area.unit == "sqft"
    assert first.property.address.postal_code == "400076"
    assert first.listing.list_price.amount == Decimal("25000000")
    assert first.listing.list_price.currency == "INR"
    assert first.listing.expires_on == date(2027, 3, 31)
    assert second.property and second.listing
    assert second.property.property_type == "house"
    assert second.listing.listing_type == "rent"
    assert second.property.area and second.property.area.unit == "sqm"
    assert second.listing.remarks is None


def test_indian_portal_file_normalises_values() -> None:
    parsed = parse(_read("portal.csv"))
    assert parsed.ready, (parsed.errors, [r.errors for r in parsed.rows])
    flat, plot, office = parsed.rows
    assert flat.property and flat.listing
    assert flat.listing.list_price.amount == Decimal("12500000")
    assert flat.property.bedrooms == 2
    assert flat.property.address.country == "IN"
    assert flat.property.address.postal_code == "400076"
    assert flat.property.area and flat.property.area.value == Decimal("1050")
    assert flat.property.area.unit == "sqft"  # from the header "Carpet Area (sq ft)"
    assert flat.listing.remarks == 'Near the lake, "ready to move"'
    assert flat.listing.expires_on == date(2027, 3, 31)  # 31/03/2027, day first
    assert plot.property and plot.listing
    assert plot.property.property_type == "plot"
    assert plot.listing.list_price.amount == Decimal("8500000")
    # 200 sq yd in the cell overrides the header's sq ft and is converted exactly.
    assert plot.property.area and plot.property.area.value == Decimal("1800")
    assert office.property and office.listing
    assert office.property.property_type == "commercial"
    assert office.listing.listing_type == "rent"
    assert office.listing.list_price.amount == Decimal("150000")
    assert flat.source["Price (INR)"] == "₹1.25 Cr"  # original cell kept
    assert flat.values["list_price"] == "12500000.00"


def test_invalid_rows_get_actionable_field_errors() -> None:
    parsed = parse(_read("invalid.csv"))
    assert not parsed.errors
    assert not parsed.ready
    first, second, third = parsed.rows

    assert set(_errors(first.errors)) == {"property_type"}
    assert "Use apartment, house, villa, plot, commercial or other" in first.errors[0].message
    assert first.errors[0].column == "Property type"

    second_errors = _errors(second.errors)
    assert set(second_errors) == {
        "listing_type",
        "list_price",
        "postal_code",
        "bedrooms",
        "area",
        "year_built",
        "expires_on",
    }
    assert "Use sale or rent" in second_errors["listing_type"]
    assert "45 lakh" in second_errors["list_price"]
    assert "six digits" in second_errors["postal_code"]
    assert "has no unit" in second_errors["area"]
    assert "not a real date" in second_errors["expires_on"]
    assert "four digits" in second_errors["year_built"]

    third_errors = _errors(third.errors)
    assert third_errors["external_id"] == 'Listing ID "X-1" is also on row 2.'
    assert third_errors["title"] == "Title is required."
    assert third_errors["address_line1"] == "Address is required."
    assert "not an area unit" in third_errors["area"]
    assert third.property is None and third.listing is None


def test_missing_and_duplicate_columns_are_file_errors() -> None:
    parsed = parse("Headline,Title,Price,City\nA,B,100,Pune\n")
    messages = {problem.field: problem.message for problem in parsed.errors}
    assert messages["title"] == 'Columns "Headline" and "Title" are all Title. Keep only one.'
    assert messages["property_type"].startswith("No column for Property type.")
    assert "PropertyType" in messages["property_type"]
    assert "listing_type" in messages and "address_line1" in messages
    assert parsed.rows == []


def test_unknown_columns_are_reported_and_ignored() -> None:
    parsed = parse(
        "Title,Property type,Listing type,Price,Address,City,Super built-up area,Facing\n"
        "A,Flat,Sale,100,1 Road,Pune,1500 sq ft,East\n"
    )
    assert parsed.ready
    assert [c.header for c in parsed.columns if c.field is None] == [
        "Super built-up area",
        "Facing",
    ]
    assert parsed.rows[0].property and parsed.rows[0].property.area is None


def test_already_imported_ids_and_row_limits() -> None:
    parsed = parse(_read("reso.csv"), already_imported={"RESO-2"})
    assert parsed.rows[0].errors == []
    assert "already been imported" in parsed.rows[1].errors[0].message

    header = "Title,Property type,Listing type,Price,Address,City\n"
    too_many = header + "A,Flat,Sale,100,1 Road,Pune\n" * (MAX_ROWS + 1)
    assert "the limit is 1,000" in parse(too_many).errors[0].message
    assert parse("").errors[0].message == "The file is empty."
    assert "no listing rows" in parse(header + ",,,\n").errors[0].message


def test_extra_cells_and_currency_conflict() -> None:
    parsed = parse(
        "Title,Property type,Listing type,Price,Currency,Address,City\n"
        "A,Flat,Sale,₹100,USD,1 Road,Pune,extra\n"
    )
    errors = _errors(parsed.rows[0].errors)
    assert "more cells than the header" in errors["row"]
    assert "price is in rupees" in errors["currency"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("4500000", Decimal("4500000")),
        ("45,00,000", Decimal("4500000")),
        ("₹ 45 lakh", Decimal("4500000")),
        ("45L", Decimal("4500000")),
        ("4.5 lacs", Decimal("450000")),
        ("1.25 crore", Decimal("12500000")),
        ("2Cr", Decimal("20000000")),
        ("INR 85000", Decimal("85000")),
        ("85k", Decimal("85000")),
        ("150000 rupees", Decimal("150000")),
    ],
)
def test_price_formats(raw: str, expected: Decimal) -> None:
    assert f.price(raw)[0] == expected


@pytest.mark.parametrize(
    ("header", "field"),
    [
        ("List Price", "list_price"),
        ("list_price", "list_price"),
        ("LIST-PRICE", "list_price"),
        ("Area (sqm)", "area"),
        ("Carpet area sq.ft.", "area"),
        ("Beds", "bedrooms"),
        ("Type", None),  # ambiguous: property type or listing type
        ("Built-up area", None),
        ("Price (sq ft)", None),  # only area headers carry a unit
    ],
)
def test_header_variants(header: str, field: str | None) -> None:
    assert f.field_for_header(header) == field


def test_every_field_lists_headers_and_help() -> None:
    for field in f.FIELDS:
        assert field.accepted_headers[0] == field.label
        assert f.field_for_header(field.label) == field.name
        if field.reso_name:
            assert f.field_for_header(field.reso_name) == field.name
        assert field.help
