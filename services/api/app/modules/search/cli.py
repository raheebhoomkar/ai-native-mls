"""Re-index every listing, e.g. after changing EMBEDDER or VECTOR_STORE:

    python -m app.modules.search.cli reindex

It only queues jobs; the worker (`python -m app.worker`) does the embedding.
"""

import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

import app.main  # noqa: F401  # importing the app registers every module and its job handlers
from app.core.db import get_engine
from app.modules.listings.models import Listing
from app.modules.search import service


def main() -> int:
    parser = argparse.ArgumentParser(description="Semantic search administration.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("reindex", help="Queue a re-index of every listing.")
    parser.parse_args()
    with Session(get_engine()) as session, session.begin():
        ids = list(session.scalars(select(Listing.id)))
        service.enqueue_reindex(session, ids)
    print(f"Queued {len(ids)} listings for re-indexing. The worker embeds them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
