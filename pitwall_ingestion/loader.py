from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import fastf1

from .config import config


# IMPORTANT:
# FastF1 otherwise initializes/uses its default macOS cache:
# ~/Library/Caches/fastf1
#
# Explicitly point FastF1 at PitWall's real project cache before
# creating/loading any sessions.
fastf1.Cache.configure(cache_dir=config.cache_dir)


@dataclass
class LoadReport:
    had_fetch_activity: bool = False
    cached_resources: list[str] = field(default_factory=list)
    fetched_resources: list[str] = field(default_factory=list)
    unavailable_resources: list[str] = field(default_factory=list)
    failed_resources: list[str] = field(default_factory=list)
    log_messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "had_fetch_activity": self.had_fetch_activity,
            "cached_resources": list(self.cached_resources),
            "fetched_resources": list(self.fetched_resources),
            "unavailable_resources": list(self.unavailable_resources),
            "failed_resources": list(self.failed_resources),
        }


class _FastF1Capture(logging.Handler):
    """Capture FastF1 log records while keeping FastF1's normal console logs."""

    def __init__(self, report: LoadReport) -> None:
        super().__init__(level=logging.INFO)
        self.report = report

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:
            return

        self.report.log_messages.append(message)
        lower = message.lower()

        # FastF1's request logger reports these messages when using its cache
        # and when it needs to acquire data from an upstream source.
        if "using cached data for " in lower:
            resource = message.split("Using cached data for ", 1)[-1].strip()
            if resource and resource not in self.report.cached_resources:
                self.report.cached_resources.append(resource)

        if "no cached data found for " in lower:
            resource = message.split("No cached data found for ", 1)[-1].split(".", 1)[0].strip()
            self.report.had_fetch_activity = True
            if resource and resource not in self.report.fetched_resources:
                self.report.fetched_resources.append(resource)

        if "fetching " in lower:
            self.report.had_fetch_activity = True

        if "data has been written to cache" in lower:
            self.report.had_fetch_activity = True

        # FastF1 uses messages such as "Car position data is unavailable!".
        # We retain the entire message; the validator can interpret it without
        # guessing a resource name from implementation-specific wording.
        if " unavailable" in lower or "unavailable!" in lower:
            self.report.had_fetch_activity = True
            if message not in self.report.unavailable_resources:
                self.report.unavailable_resources.append(message)

        if "failed to load" in lower or "failed to determine" in lower:
            self.report.had_fetch_activity = True
            if message not in self.report.failed_resources:
                self.report.failed_resources.append(message)


def _capture_handler(report: LoadReport) -> tuple[logging.Handler, list[tuple[logging.Logger, int, bool]]]:
    """Attach one temporary handler high enough to capture FastF1's loggers."""
    handler = _FastF1Capture(report)
    root = logging.getLogger()
    previous = [(root, root.level, handler in root.handlers)]
    root.addHandler(handler)

    # FastF1 commonly uses these named loggers and may set their own level.
    for name in ("core", "req", "_api", "logger", "fastf1"):
        logger = logging.getLogger(name)
        previous.append((logger, logger.level, handler in logger.handlers))
        logger.addHandler(handler)
        if logger.level == logging.NOTSET or logger.level > logging.INFO:
            logger.setLevel(logging.INFO)

    return handler, previous


def _remove_capture_handler(handler: logging.Handler, previous: list[tuple[logging.Logger, int, bool]]) -> None:
    seen: set[int] = set()
    for logger, level, had_handler in previous:
        if id(logger) in seen:
            continue
        seen.add(id(logger))
        if handler in logger.handlers:
            logger.removeHandler(handler)
        logger.setLevel(level)
    handler.close()


def load_complete_candidate(planned) -> tuple[Any, LoadReport]:
    """
    Load one Race or Qualifying session through FastF1's normal cache/fetch path.

    FastF1's built-in request-level rate limiter is untouched.  The returned
    LoadReport records whether FastF1 reported cached resources, fetch activity,
    unavailable resources, or load failures.
    """
    report = LoadReport()
    
    print(
        f"[FastF1] Active cache: {config.cache_dir}",
        flush=True,
    )
    
    handler, previous = _capture_handler(report)
    try:
        session = fastf1.get_session(
            planned.year,
            planned.round_number,
            planned.session_type,
        )

        if planned.session_type == "R":
            session.load(
                laps=True,
                telemetry=True,
                weather=True,
                messages=True,
            )
        else:
            session.load(
                laps=True,
                telemetry=True,
                weather=False,
                messages=False,
            )

        return session, report
    finally:
        _remove_capture_handler(handler, previous)
