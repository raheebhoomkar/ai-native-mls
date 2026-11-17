from typing import Annotated

from pydantic import BaseModel, Field

from app.modules.listings.schemas import ListingFilters, ListingOut

DEMO_NOTE = "Demo embedder: it matches shared words and spellings, not meaning."


class SearchFilters(ListingFilters):
    q: Annotated[
        str,
        Field(
            min_length=1,
            max_length=500,
            pattern=r"\S",
            description="Describe the home in your own words.",
        ),
    ]
    limit: Annotated[int, Field(ge=1, le=50)] = 20


class Explanation(BaseModel):
    matched_words: list[str] = Field(description="Words of the query found in the listing.")
    filters: list[str] = Field(description="Filters that narrowed the candidates.")
    source: str = Field(description="Embedder: demo or gemini.")
    model: str
    note: str | None = Field(description="Set when results need a caveat, e.g. the demo embedder.")


class SearchHit(BaseModel):
    listing: ListingOut
    score: float = Field(description="Cosine similarity of the query and the listing, -1 to 1.")
    explanation: Explanation


class SearchResults(BaseModel):
    items: list[SearchHit]
    next_cursor: None = Field(default=None, description="Always null: one ranked page.")
