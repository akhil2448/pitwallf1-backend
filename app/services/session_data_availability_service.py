
import json
from pathlib import Path

from app.config.settings import settings


class SessionDataAvailabilityService:
    """Read ingestion statuses from the existing session manifest."""

    def __init__(self, manifest_path: Path | None = None):
        self.manifest_path = (
            Path(manifest_path)
            if manifest_path is not None
            else settings.SESSION_MANIFEST_PATH
        )

    def get_session_status(self, year: int, round_number: int, session_code: str) -> str:
        """Return the manifest status, or 'missing' if no record exists."""
        key = f"{year}-{round_number:02d}-{session_code}"

        try:
            with self.manifest_path.open("r", encoding="utf-8") as file:
                manifest = json.load(file)
        except FileNotFoundError:
            return "missing"
        except (json.JSONDecodeError, OSError):
            return "missing"

        record = manifest.get("sessions", {}).get(key)

        if not isinstance(record, dict):
            return "missing"

        status = record.get("status", "missing")
        return status if isinstance(status, str) else "missing"

    def is_session_available(
        self, year: int, round_number: int, session_code: str
    ) -> bool:
        return (
            self.get_session_status(year, round_number, session_code)
            == "complete"
        )
