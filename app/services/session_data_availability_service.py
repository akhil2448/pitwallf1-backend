
import json
from pathlib import Path
import logging

from app.config.settings import settings

logger = logging.getLogger(__name__)

class SessionDataAvailabilityService:
    """Read ingestion statuses from the existing session manifest."""

    def __init__(self, manifest_path: Path | None = None):
        self.manifest_path = (
            Path(manifest_path)
            if manifest_path is not None
            else settings.SESSION_MANIFEST_PATH
        )

    def get_session_status(
        self,
        year: int,
        round_number: int,
        session_code: str,
    ) -> str | None:
        """Return the manifest status, or None if it cannot be determined."""

        key = f"{year}-{round_number:02d}-{session_code}"

        try:
            with self.manifest_path.open("r", encoding="utf-8") as file:
                manifest = json.load(file)

            if not isinstance(manifest, dict):
                return None

            sessions = manifest.get("sessions")

            if not isinstance(sessions, dict):
                return None

            record = sessions.get(key)

            if not isinstance(record, dict):
                return None

            status = record.get("status")

            return status if isinstance(status, str) else None

        except Exception:
            # Availability is optional; do not break schedule generation.
            logger.debug(
                "Unable to determine session status for %s",
                key,
                exc_info=True,
            )
            return None

    def is_session_available(
        self, year: int, round_number: int, session_code: str
    ) -> bool:
        return (
            self.get_session_status(year, round_number, session_code)
            == "complete"
        )
