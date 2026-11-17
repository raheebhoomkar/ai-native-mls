"""Background job worker: `python -m app.worker`.

Runs jobs one at a time until stopped with SIGINT or SIGTERM; the job in progress
finishes first. Start more processes to run jobs in parallel.
"""

import logging
import signal
import threading
import time
from types import FrameType

from sqlalchemy.orm import Session

import app.main  # noqa: F401  # importing the app registers every module and its job handlers
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.logging import configure_logging
from app.modules.jobs import service as jobs
from app.modules.ops import service as ops

logger = logging.getLogger("app.worker")

POLL_SECONDS = 2.0
# How often the worker checks that the daily cleanup is queued.
SCHEDULE_SECONDS = 3600.0


def main() -> None:
    configure_logging(get_settings().log_level)
    stop = threading.Event()

    def _stop(signum: int, _frame: FrameType | None) -> None:
        logger.info("Stopping worker", extra={"signal": signum})
        stop.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    logger.info("Worker started")
    next_schedule = 0.0
    while not stop.is_set():
        if time.monotonic() >= next_schedule:
            next_schedule = time.monotonic() + SCHEDULE_SECONDS
            try:
                with Session(get_engine()) as session:
                    ops.ensure_cleanup_scheduled(session)
            except Exception:
                logger.exception("Could not schedule the cleanup")
        try:
            with Session(get_engine()) as session:
                ran = jobs.run_one(session)
        except Exception:
            # Database unreachable or similar; do not spin. The job, if any, is reclaimed later.
            logger.exception("Worker loop error")
            ran = False
        if not ran:
            stop.wait(POLL_SECONDS)


if __name__ == "__main__":
    main()
