
import json
import tempfile
import unittest
from pathlib import Path

from app.services.session_data_availability_service import (
    SessionDataAvailabilityService,
)


class SessionDataAvailabilityServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.manifest_path = Path(self.temp_dir.name) / "manifest.json"

        self.manifest_path.write_text(
            json.dumps({
                "sessions": {
                    "2026-07-Q": {"status": "complete"},
                    "2026-07-R": {"status": "failed"},
                }
            }),
            encoding="utf-8",
        )

        self.service = SessionDataAvailabilityService(self.manifest_path)

    def test_complete_session_is_available(self):
        self.assertTrue(
            self.service.is_session_available(2026, 7, "Q")
        )

    def test_failed_session_is_not_available(self):
        self.assertFalse(
            self.service.is_session_available(2026, 7, "R")
        )

    def test_missing_session_returns_none_and_is_unavailable(self):
        self.assertIsNone(
            self.service.get_session_status(2026, 8, "R")
        )

        self.assertFalse(
            self.service.is_session_available(2026, 8, "R")
        )

    def test_missing_manifest_is_not_available(self):
        service = SessionDataAvailabilityService(
            Path(self.temp_dir.name) / "missing.json"
        )
        self.assertFalse(
            service.is_session_available(2026, 7, "Q")
        )
    
    def test_invalid_manifest_returns_none(self):
        self.manifest_path.write_text(
            "{invalid json",
            encoding="utf-8",
        )

        self.assertIsNone(
            self.service.get_session_status(2026, 7, "Q")
        )


if __name__ == "__main__":
    unittest.main()
