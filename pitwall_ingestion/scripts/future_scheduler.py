from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pitwall_ingestion.config import config
from pitwall_ingestion.notify import publish_oci_notification
from pitwall_ingestion.schedule import read_schedule_snapshot


def _load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Could not read JSON file {path}: {exc}") from exc


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _pending_sessions(schedule: dict, manifest: dict, now: datetime) -> list[dict]:
    complete = {
        key
        for key, record in manifest.get("sessions", {}).items()
        if record.get("status") == "complete"
    }

    sessions = schedule.get("sessions", [])

    # A weekend becomes actionable only after its Race has finished
    # and the scheduler buffer has elapsed.
    race_dates: dict[tuple[object, object], datetime] = {}

    for item in sessions:
        if item.get("session_type") != "R":
            continue

        year = item.get("year")
        round_number = item.get("round_number")
        race_date = _parse_dt(item.get("session_date"))

        if year is None or round_number is None or race_date is None:
            continue

        race_dates[(year, round_number)] = race_date

    pending: list[dict] = []
    cutoff = timedelta(hours=config.race_completion_buffer_hours)

    for item in sessions:
        # The scheduler only needs to track Qualifying and Race.
        if item.get("session_type") not in {"Q", "R"}:
            continue

        key = item.get("key")
        year = item.get("year")
        round_number = item.get("round_number")

        if not key or year is None or round_number is None:
            continue

        race_date = race_dates.get((year, round_number))

        # Do not consider a weekend actionable unless its Race exists
        # in the schedule and has passed the completion buffer.
        if race_date is None:
            continue

        if race_date + cutoff > now:
            continue

        if key in complete:
            continue

        pending.append(item)

    return sorted(
        pending,
        key=lambda item: (
            item.get("year", 0),
            item.get("round_number", 0),
            0 if item.get("session_type") == "Q" else 1,
        ),
    )


def _missing_schedule_years(schedule: dict, now: datetime) -> list[int]:
    current_year = now.year
    years = {int(year) for year in schedule.get("years", [])}
    if current_year not in years:
        return [current_year]
    return []


def _backlog_payload(
    pending: list[dict],
    missing_schedule_years: list[int],
) -> dict:
    return {
        "missing_schedule_years": sorted(missing_schedule_years),
        "pending_keys": sorted(
            item.get("key")
            for item in pending
            if item.get("key")
        ),
    }


def _backlog_hash(payload: dict) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _email_body(
    pending: list[dict],
    missing_schedule_years: list[int],
    manifest_missing: bool,
    now: datetime,
) -> str:
    lines = [
        "PitWall — F1 data requires your attention",
        "",
    ]

    if manifest_missing:
        lines.append("SERVER MANIFEST NEEDS TO BE INITIALIZED")
        lines.extend([
            "- The Oracle session manifest is missing, so the scheduler will not guess which historical sessions are already cached.",
            "- Initialize/publish the session manifest from the verified archive before enabling normal pending-session reminders.",
            "",
        ])

    if missing_schedule_years:
        lines.append("SEASON SCHEDULE NEEDS TO BE LOADED LOCALLY")
        for year in missing_schedule_years:
            lines.append(
                f"- {year} season schedule is not available on the server."
            )
        lines.extend(
            [
                "",
                "Run this locally when FastF1 has the new schedule:",
                "python scripts/refresh_schedule.py "
                f"--year {missing_schedule_years[0]}",
                "",
            ]
        )

    if pending:
        lines.append("PENDING SESSIONS")
        grouped: dict[tuple[int, str], list[dict]] = {}

        for item in pending:
            grouped.setdefault(
                (int(item["year"]), str(item["event_name"])),
                [],
            ).append(item)

        for (year, event_name), sessions in sorted(grouped.items()):
            lines.append(f"{year} {event_name}")
            for session in sorted(
                sessions,
                key=lambda x: 0 if x.get("session_type") == "Q" else 1,
            ):
                label = (
                    "Qualifying"
                    if session.get("session_type") == "Q"
                    else "Race"
                )
                lines.append(f"  - {label}")
            lines.append("")

        lines.append(f"Total pending sessions: {len(pending)}")
        lines.append("")
        lines.append("Run locally:")
        lines.append("python scripts/future_ingestion.py")

    lines.extend(
        [
            "",
            f"Generated: {now.isoformat()}",
            "",
            "This is a consolidated backlog. Sessions disappear from future "
            "reminders after they are successfully synced to Oracle.",
        ]
    )

    return "\n".join(lines)


def should_notify(
    state: dict,
    backlog_hash: str,
    now: datetime,
) -> tuple[bool, str]:
    previous_hash = state.get("last_backlog_hash")
    last_notified = _parse_dt(state.get("last_notification_at"))

    if previous_hash != backlog_hash:
        return True, "backlog changed"

    if last_notified is None:
        return True, "no previous notification"

    if now - last_notified >= timedelta(
        hours=config.reminder_interval_hours
    ):
        return True, "reminder interval reached"

    return False, "reminder not due"


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Oracle-side, FastF1-free scheduler. It reads the local schedule "
            "snapshot and session manifest and sends one consolidated OCI "
            "email when data needs attention."
        )
    )
    parser.add_argument(
        "--schedule",
        type=Path,
        default=Path(config.oracle_schedule_path),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(config.oracle_manifest_path),
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=Path(config.oracle_scheduler_state_path),
    )
    parser.add_argument(
        "--force-email",
        action="store_true",
        help="Send the current consolidated backlog email immediately.",
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc)

    if not args.schedule.exists():
        schedule = {"schema_version": 1, "years": [], "sessions": []}
        print(
            f"[{now.isoformat()}] Schedule snapshot missing: {args.schedule}"
        )
    else:
        try:
            schedule = read_schedule_snapshot(args.schedule)
        except Exception as exc:
            print(f"[SCHEDULE ERROR] {exc}")
            return 1

    manifest_missing = not args.manifest.exists()
    manifest = _load_json(
        args.manifest,
        {
            "schema_version": 1,
            "sessions": {},
        },
    )

    pending = [] if manifest_missing else _pending_sessions(schedule, manifest, now)
    missing_schedule_years = _missing_schedule_years(schedule, now)

    payload = _backlog_payload(pending, missing_schedule_years)
    payload["manifest_missing"] = manifest_missing
    backlog_hash = _backlog_hash(payload)

    state = _load_json(args.state, {})

    action_required = (
        bool(pending)
        or bool(missing_schedule_years)
        or manifest_missing
    )

    if not action_required:
        notify = False
        reason = "nothing requires attention"

        # Clear the previous backlog so that if a new backlog
        # appears later, it is treated as a new event immediately.
        state.update(
            {
                "last_backlog_hash": None,
                "last_pending_count": 0,
                "last_missing_schedule_years": [],
                "manifest_missing": False,
            }
        )
        save_state(args.state, state)
    else:
        notify, reason = should_notify(state, backlog_hash, now)

    if args.force_email:
        notify, reason = True, "forced"

    print(
        f"[{now.isoformat()}] Scheduler check: "
        f"{len(pending)} pending sessions; "
        f"missing schedules={missing_schedule_years}; "
        f"notification={notify} ({reason})",
        flush=True,
    )

    if not notify:
        return 0

    body = _email_body(
        pending,
        missing_schedule_years,
        manifest_missing,
        now,
    )

    title_parts = ["PitWall"]
    if manifest_missing:
        title_parts.append("server manifest required")
    elif missing_schedule_years:
        title_parts.append("schedule update required")
    elif pending:
        title_parts.append(f"{len(pending)} session(s) pending")
    else:
        title_parts.append("F1 data update")

    title = " — ".join(title_parts)

    try:
        publish_oci_notification(title, body)
    except Exception as exc:
        print(f"[EMAIL FAILED] {exc}", flush=True)
        return 1

    state.update(
        {
            "last_backlog_hash": backlog_hash,
            "last_notification_at": now.isoformat(),
            "last_pending_count": len(pending),
            "last_missing_schedule_years": missing_schedule_years,
            "manifest_missing": manifest_missing,
        }
    )
    save_state(args.state, state)

    print(
        f"[{now.isoformat()}] Email sent successfully.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
