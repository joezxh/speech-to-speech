from __future__ import annotations

import sys

from loguru import logger


def configure_logging(level: str = "info") -> None:
    """stdout only: supervisord captures it, `docker logs` merges both programs.

    Deliberately does not touch the root stdlib logger — the pipeline owns its
    own logging configuration in the same container (spec D13).
    """
    logger.remove()
    logger.add(
        sys.stdout,
        level=level.upper(),
        enqueue=False,
        format="{time:YYYY-MM-DDTHH:mm:ss.SSSZ} {level} {name} {message}",
    )
