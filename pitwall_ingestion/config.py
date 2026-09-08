from __future__ import annotations

import os
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    return float(value)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE_DIR = PROJECT_ROOT / "cache"
DEFAULT_METADATA_DIR = PROJECT_ROOT / ".pitwall-ingestion"


@dataclass(frozen=True)
class IngestionConfig:
    # Resolve the repository cache independently of the current working directory.
    # Override with FASTF1_CACHE_DIR when intentionally using another cache.
    cache_dir: Path = Path(os.getenv("FASTF1_CACHE_DIR", str(DEFAULT_CACHE_DIR))).expanduser().resolve()
    metadata_dir: Path = Path(
        os.getenv("PITWALL_INGESTION_METADATA_DIR", str(DEFAULT_METADATA_DIR))
    ).expanduser().resolve()

    start_year: int = _env_int("PITWALL_START_YEAR", 2018)
    current_year: int = _env_int(
        "PITWALL_CURRENT_YEAR",
        datetime.now(timezone.utc).year,
    )

    # Future-ingestion safety: wait for a short period after a session
    # finishes so upstream data has time to settle.
    session_completion_buffer_hours: float = _env_float(
        "PITWALL_SESSION_COMPLETION_BUFFER_HOURS", 3.0
    )
    
    # Oracle scheduler safety: a qualifying session is not considered
    # actionable until the race for that weekend has finished and this
    # buffer has elapsed. This allows the complete race weekend to be
    # ingested together.
    race_completion_buffer_hours: float = _env_float(
        "PITWALL_RACE_COMPLETION_BUFFER_HOURS", 3.0
    )

    # Reminder cadence for the Oracle-side scheduler. A changed pending
    # backlog triggers an email immediately; an unchanged backlog is reminded
    # only after this interval.
    reminder_interval_hours: float = _env_float(
        "PITWALL_PENDING_REMINDER_INTERVAL_HOURS", 72.0
    )

    # Oracle-side schedule/manifest/notification state.
    oracle_schedule_path: str = os.getenv(
        "ORACLE_SCHEDULE_PATH", "/opt/pitwall/metadata/schedule_snapshot.json"
    )
    oracle_scheduler_state_path: str = os.getenv(
        "ORACLE_SCHEDULER_STATE_PATH",
        "/opt/pitwall/metadata/future_scheduler_state.json",
    )

    # OCI Notifications topic used by the Oracle scheduler. The OCI CLI is
    # used on Oracle so no mailbox password/SMTP secret is stored in PitWall.
    oci_notifications_topic_ocid: str = os.getenv(
        "OCI_NOTIFICATIONS_TOPIC_OCID", ""
    )

    # Absolute OCI CLI path for cron environments with a minimal PATH.
    oci_cli_path: str = os.getenv("OCI_CLI_PATH", "")

    # Additional delay between completed session loads. FastF1's own
    # request-level limiter remains untouched and continues to control the
    # individual upstream requests inside session.load().
    session_cooldown_seconds: float = _env_float(
        "PITWALL_SESSION_COOLDOWN_SECONDS", 120.0
    )

    # How many sessions one invocation is allowed to complete. Use a small
    # number for unattended daily operation; resume state makes it safe.
    max_sessions_per_run: int = _env_int("PITWALL_MAX_SESSIONS_PER_RUN", 2)

    oracle_host: str = os.getenv("ORACLE_HOST", "")
    oracle_user: str = os.getenv("ORACLE_USER", "")
    oracle_ssh_key: Path | None = (
        Path(os.environ["ORACLE_SSH_KEY"])
        if os.getenv("ORACLE_SSH_KEY")
        else None
    )
    oracle_cache_dir: str = os.getenv("ORACLE_CACHE_DIR", "/opt/pitwall/cache")
    oracle_manifest_path: str = os.getenv(
        "ORACLE_MANIFEST_PATH", "/opt/pitwall/metadata/session_manifest.json"
    )
    oracle_staging_dir: str = os.getenv(
        "ORACLE_STAGING_DIR", "/opt/pitwall/cache/.staging"
    )
    sync_to_oracle: bool = _env_bool("PITWALL_SYNC_TO_ORACLE", True)

    # Version policy. We detect newer releases but never silently upgrade a
    # running archive. An explicit dependency update command is safer.
    fail_on_newer_fastf1: bool = _env_bool(
        "PITWALL_FAIL_ON_NEWER_FASTF1", False
    )


config = IngestionConfig()
