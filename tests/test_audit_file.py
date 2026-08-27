"""Checks for bounded, injection-resistant local audit storage."""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from uuid import UUID

from personal_assistant.audit import (
    AuditComponent,
    AuditEvent,
    AuditMetadataItem,
    AuditMetadataKey,
    AuditOperation,
    AuditOutcome,
    AuditReasonCode,
    AuditValidationError,
    AuditWriteError,
)
from personal_assistant.audit_file import (
    AuditFileSettings,
    JsonLinesAuditReader,
    JsonLinesAuditSink,
)


def audit_event(index: int = 1) -> AuditEvent:
    return AuditEvent(
        event_id=UUID(int=index),
        correlation_id=UUID(int=100 + index),
        timestamp=(
            datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
            + timedelta(seconds=index)
        ),
        component=AuditComponent.DATABASE,
        operation=AuditOperation.REPOSITORY_READ,
        outcome=AuditOutcome.SUCCEEDED,
        reason_code=AuditReasonCode.NORMAL,
        duration_ms=index,
        metadata=(
            AuditMetadataItem(AuditMetadataKey.ITEM_COUNT, index),
            AuditMetadataItem(AuditMetadataKey.RECORD_ID, f"record-{index}"),
        ),
    )


class AuditFileSettingsTests(unittest.TestCase):
    def test_path_must_be_absolute_and_limits_must_be_bounded(self) -> None:
        with self.assertRaisesRegex(ValueError, "absolute path"):
            AuditFileSettings(Path("audit.jsonl"))
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            AuditFileSettings(
                Path.cwd() / "audit.jsonl",
                max_file_bytes=100,
                max_event_bytes=101,
            )
        with self.assertRaisesRegex(ValueError, "between 0 and"):
            AuditFileSettings(
                Path.cwd() / "audit.jsonl",
                retained_rotations=21,
            )
        with self.assertRaisesRegex(ValueError, "bounded positive integer"):
            AuditFileSettings(
                Path.cwd() / "audit.jsonl",
                max_file_bytes=67_108_865,
            )
        for setting_name, setting_value in (
            ("max_file_bytes", 1.5),
            ("max_event_bytes", True),
            ("retained_rotations", 2.5),
        ):
            with self.subTest(setting_name=setting_name):
                arguments = {setting_name: setting_value}
                with self.assertRaises(ValueError):
                    AuditFileSettings(
                        Path.cwd() / "audit.jsonl",
                        **arguments,  # type: ignore[arg-type]
                    )


class JsonLinesAuditSinkTests(unittest.TestCase):
    def test_event_is_one_structured_line_with_restrictive_permissions(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "private" / "audit.jsonl"
            sink = JsonLinesAuditSink(AuditFileSettings(path))

            sink.write(audit_event())

            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            document = json.loads(lines[0])
            self.assertEqual(document["operation"], "repository_read")
            self.assertEqual(document["metadata"]["record_id"], "record-1")
            self.assertNotIn("prompt", document)
            self.assertNotIn("response", document)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(
                    stat.S_IMODE(path.parent.stat().st_mode),
                    0o700,
                )

    @unittest.skipUnless(os.name == "posix", "POSIX permission bits unavailable")
    def test_existing_file_permissions_are_restricted(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "audit.jsonl"
            path.write_text("", encoding="utf-8")
            path.chmod(0o644)
            sink = JsonLinesAuditSink(AuditFileSettings(path))

            sink.write(audit_event())

            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_rotation_and_retention_keep_only_configured_files(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "audit.jsonl"
            sink = JsonLinesAuditSink(
                AuditFileSettings(
                    path,
                    max_file_bytes=420,
                    max_event_bytes=420,
                    retained_rotations=2,
                )
            )

            for index in range(1, 9):
                sink.write(audit_event(index))

            self.assertTrue(path.exists())
            self.assertTrue(Path(f"{path}.1").exists())
            self.assertTrue(Path(f"{path}.2").exists())
            self.assertFalse(Path(f"{path}.3").exists())
            for retained_path in (path, Path(f"{path}.1"), Path(f"{path}.2")):
                self.assertLessEqual(retained_path.stat().st_size, 420)

    def test_oversized_event_is_rejected_before_disk_write(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "audit.jsonl"
            sink = JsonLinesAuditSink(
                AuditFileSettings(
                    path,
                    max_file_bytes=256,
                    max_event_bytes=128,
                )
            )

            with self.assertRaisesRegex(AuditValidationError, "too large"):
                sink.write(audit_event())

            self.assertFalse(path.exists())

    def test_unsafe_existing_target_fails_without_exposing_path(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "audit.jsonl"
            path.mkdir()
            sink = JsonLinesAuditSink(AuditFileSettings(path))

            with self.assertRaises(AuditWriteError) as raised:
                sink.write(audit_event())

            self.assertEqual(
                str(raised.exception),
                "Audit event could not be recorded.",
            )
            self.assertNotIn(temporary_directory, str(raised.exception))

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links unavailable")
    def test_symbolic_link_target_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            target = directory / "target.txt"
            target.write_text("unchanged", encoding="utf-8")
            path = directory / "audit.jsonl"
            try:
                path.symlink_to(target)
            except OSError:
                self.skipTest("symbolic links cannot be created")
            sink = JsonLinesAuditSink(AuditFileSettings(path))

            with self.assertRaisesRegex(AuditWriteError, "could not be recorded"):
                sink.write(audit_event())

            self.assertEqual(target.read_text(encoding="utf-8"), "unchanged")

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links unavailable")
    def test_symbolic_link_parent_directory_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "target"
            target.mkdir()
            linked_parent = root / "linked"
            try:
                linked_parent.symlink_to(target, target_is_directory=True)
            except OSError:
                self.skipTest("symbolic links cannot be created")
            sink = JsonLinesAuditSink(
                AuditFileSettings(linked_parent / "audit.jsonl")
            )

            with self.assertRaisesRegex(AuditWriteError, "could not be recorded"):
                sink.write(audit_event())

            self.assertEqual(tuple(target.iterdir()), ())


class JsonLinesAuditReaderTests(unittest.TestCase):
    def test_reader_is_newest_first_paginated_and_content_minimized(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "audit.jsonl"
            settings = AuditFileSettings(path)
            sink = JsonLinesAuditSink(settings)
            for index in range(1, 106):
                sink.write(audit_event(index))

            reader = JsonLinesAuditReader(settings)
            first = reader.read_page()
            second = reader.read_page(first.next_offset or 0)

            self.assertEqual(len(first.items), 100)
            self.assertEqual(len(second.items), 5)
            self.assertEqual(first.items[0].operation, "repository_read")
            self.assertEqual(first.items[0].timestamp, "2026-08-24T12:01:45.000Z")
            self.assertIsNone(second.next_offset)
            serialized = repr(first.items)
            self.assertNotIn("record-105", serialized)
            self.assertNotIn("correlation", serialized)

    def test_reader_skips_malformed_content_and_rejects_symlink(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            path = root / "audit.jsonl"
            path.write_text('{"prompt":"must not display"}\n', encoding="utf-8")
            with self.assertRaisesRegex(AuditWriteError, "invalid entry"):
                JsonLinesAuditReader(AuditFileSettings(path)).read_page()
            if hasattr(os, "symlink"):
                linked = root / "linked.jsonl"
                try:
                    linked.symlink_to(path)
                except OSError:
                    return
                with self.assertRaises(AuditWriteError):
                    JsonLinesAuditReader(AuditFileSettings(linked)).read_page()
