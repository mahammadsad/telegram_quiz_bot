"""Centralized logging setup so every entrypoint (main.py, sync_poll_answers.py)
logs in the same format instead of each script re-calling basicConfig."""

from __future__ import annotations

import logging


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
