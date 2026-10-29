from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from .config import config


@dataclass(frozen=True)
class PlannedSession:
    key: str
    year: int
    round_number: int
    session_type: str
    event_name: str
    session_date: datetime | None


def _as_utc(value) -> datetime | None:
    import pandas as pd

    if pd.isna(value):
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.to_pydatetime().astimezone(timezone.utc)


def build_schedule(
    years: Iterable[int],
    *,
    only_sessions_ended_by: datetime | None = None,
) -> list[PlannedSession]:
    import fastf1

    # Configure FastF1 only when we actually fetch a schedule. This keeps
    # Oracle-side scheduler imports FastF1-free and prevents default-cache
    # creation on the server.
    fastf1.Cache.configure(cache_dir=config.cache_dir)

    now = only_sessions_ended_by or datetime.now(timezone.utc)
    planned: list[PlannedSession] = []

    for year in years:
        df = fastf1.get_event_schedule(year)
        df = df[df["RoundNumber"] > 0]

        for _, row in df.iterrows():
            round_number = int(row["RoundNumber"])
            event_name = str(row["EventName"])

            q_date = _as_utc(row.get("Session4DateUtc"))
            r_date = _as_utc(row.get("Session5DateUtc"))

            for code, session_date in (("Q", q_date), ("R", r_date)):
                if session_date is None:
                    continue
                planned.append(
                    PlannedSession(
                        key=f"{year}-{round_number:02d}-{code}",
                        year=year,
                        round_number=round_number,
                        session_type=code,
                        event_name=event_name,
                        session_date=session_date,
                    )
                )

    return sorted(
        planned,
        key=lambda x: (
            x.year,
            x.round_number,
            0 if x.session_type == "Q" else 1,
        ),
    )


def schedule_to_dict(sessions: Iterable[PlannedSession]) -> dict:
    """Serialize planned sessions for use by the Oracle-side scheduler."""
    items = []
    for session in sessions:
        items.append(
            {
                "key": session.key,
                "year": session.year,
                "round_number": session.round_number,
                "session_type": session.session_type,
                "event_name": session.event_name,
                "session_date": (
                    session.session_date.astimezone(timezone.utc).isoformat()
                    if session.session_date
                    else None
                ),
            }
        )
    years = sorted({item["year"] for item in items})
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "years": years,
        "sessions": items,
    }


def write_schedule_snapshot(sessions: Iterable[PlannedSession], path) -> None:
    import json
    from pathlib import Path

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(schedule_to_dict(sessions), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def merge_schedule_snapshot(existing_path, sessions: Iterable[PlannedSession]) -> dict:
    """Merge newly fetched sessions into an existing local schedule snapshot."""
    import json
    from pathlib import Path

    target = Path(existing_path)
    existing = {}
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    by_key = {
        item["key"]: item
        for item in existing.get("sessions", [])
        if item.get("key")
    }

    new_sessions = list(sessions)
    for item in schedule_to_dict(new_sessions)["sessions"]:
        by_key[item["key"]] = item

    merged = sorted(
        by_key.values(),
        key=lambda item: (
            int(item.get("year", 0)),
            int(item.get("round_number", 0)),
            0 if item.get("session_type") == "Q" else 1,
        ),
    )

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "years": sorted({int(item["year"]) for item in merged}),
        "sessions": merged,
    }


def write_merged_schedule_snapshot(
    existing_path, sessions: Iterable[PlannedSession]
) -> None:
    import json
    from pathlib import Path

    target = Path(existing_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(merge_schedule_snapshot(target, sessions), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def read_schedule_snapshot(path) -> dict:
    import json
    from pathlib import Path

    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(
            f"Schedule snapshot does not exist: {target}"
        )
    data = json.loads(target.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise RuntimeError(
            f"Unsupported schedule snapshot schema: {data.get('schema_version')}"
        )
    return data
