from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.imports.validation import MAX_CHARS


class FieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    label: str
    # The closest RESO Data Dictionary field. Alignment only; no conformance is claimed.
    reso_name: str | None
    required: bool
    # Headers recognised for this field. Case, spaces and punctuation are ignored.
    accepted_headers: list[str]
    help: str


class ImportRequest(BaseModel):
    filename: Annotated[str, Field(min_length=1, max_length=200)]
    content: Annotated[
        str,
        Field(max_length=MAX_CHARS, description="CSV text, UTF-8; the first row is the header."),
    ]


class ProblemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # A canonical field name, "file" for the whole file, or "row" for the whole row.
    field: str
    column: str | None
    message: str


class ColumnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    header: str
    # None: not recognised, and ignored.
    field: str | None


class RowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    number: int
    external_id: str | None
    # Normalised values by canonical field, as text.
    values: dict[str, str]
    errors: list[ProblemOut]


class PreviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    columns: list[ColumnOut]
    errors: list[ProblemOut]
    rows: list[RowOut]
    # True when the file can be imported as it is.
    ready: bool


class ImportedListingOut(BaseModel):
    row_number: int
    listing_id: UUID
    title: str


class ImportOut(BaseModel):
    id: UUID
    filename: str
    created_at: datetime
    listings: list[ImportedListingOut]


class ImportSourceOut(BaseModel):
    import_id: UUID
    filename: str
    row_number: int
    external_id: str | None
    imported_at: datetime
    # The original cells of the recognised columns, by header.
    source: dict[str, str]
