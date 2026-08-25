"""End-to-end checks for trusted local memory administration."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import personal_assistant.memory_admin as memory_admin
from personal_assistant.config import AppSettings, MemorySettings


RECOVERY = "synthetic admin recovery phrase"
PASSCODE = "synthetic-admin-2468"


class MemoryAdminTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.data_directory = self.root / "private"
        self.backup_directory = self.root / "external-backups"
        self.backup_directory.mkdir()
        self.settings = AppSettings(
            memory=MemorySettings(
                data_directory=self.data_directory,
                backup_directory=self.backup_directory,
            )
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _run_setup(self) -> list[str]:
        output: list[str] = []
        with (
            patch.object(memory_admin, "load_settings", return_value=self.settings),
            patch.object(
                memory_admin,
                "getpass",
                side_effect=[RECOVERY, RECOVERY, PASSCODE, PASSCODE],
            ),
            patch("builtins.print", side_effect=lambda *parts: output.append(
                " ".join(str(part) for part in parts)
            )),
        ):
            memory_admin.main(["setup"])
        return output

    def test_setup_creates_recoverable_encrypted_runtime_without_echoing_secrets(
        self,
    ) -> None:
        output = self._run_setup()

        self.assertTrue((self.data_directory / "security.json").is_file())
        self.assertTrue((self.data_directory / "memory.db").is_file())
        combined_output = "\n".join(output)
        self.assertNotIn(RECOVERY, combined_output)
        self.assertNotIn(PASSCODE, combined_output)
        self.assertNotIn(
            RECOVERY,
            (self.data_directory / "audit.jsonl").read_text(encoding="utf-8"),
        )
        self.assertNotIn(
            PASSCODE,
            (self.data_directory / "audit.jsonl").read_text(encoding="utf-8"),
        )

    def test_cancelled_restore_never_requests_passcode_or_replaces_database(
        self,
    ) -> None:
        self._run_setup()
        with (
            patch.object(memory_admin, "load_settings", return_value=self.settings),
            patch.object(memory_admin, "getpass", return_value=RECOVERY),
            patch("builtins.print"),
        ):
            memory_admin.main(["backup"])
        snapshot_name = next(self.backup_directory.glob("memory-*.db")).name
        before = (self.data_directory / "memory.db").read_bytes()
        output: list[str] = []
        with (
            patch.object(memory_admin, "load_settings", return_value=self.settings),
            patch.object(memory_admin, "getpass", return_value=RECOVERY) as get_secret,
            patch("builtins.input", return_value="CANCEL"),
            patch("builtins.print", side_effect=lambda *parts: output.append(
                " ".join(str(part) for part in parts)
            )),
        ):
            memory_admin.main(["restore", snapshot_name])

        self.assertEqual(get_secret.call_count, 1)
        self.assertIn("Restore cancelled", "\n".join(output))
        self.assertEqual((self.data_directory / "memory.db").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
