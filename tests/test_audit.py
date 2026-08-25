"""Checks for typed, content-minimizing audit events."""

from datetime import datetime
import unittest
from uuid import uuid4

from personal_assistant.audit import (
    AuditComponent,
    AuditEvent,
    AuditMetadataItem,
    AuditMetadataKey,
    AuditOperation,
    AuditOutcome,
    AuditReasonCode,
    AuditSink,
    AuditValidationError,
    InMemoryAuditSink,
)


def audit_event(
    *, metadata: tuple[AuditMetadataItem, ...] = ()
) -> AuditEvent:
    return AuditEvent(
        correlation_id=uuid4(),
        component=AuditComponent.AUTHORIZATION,
        operation=AuditOperation.PERMISSION_EVALUATE,
        outcome=AuditOutcome.DENIED,
        reason_code=AuditReasonCode.POLICY_DENIED,
        metadata=metadata,
    )


class AuditEventTests(unittest.TestCase):
    def test_in_memory_sink_matches_replaceable_contract(self) -> None:
        sink = InMemoryAuditSink()
        event = audit_event()

        self.assertIsInstance(sink, AuditSink)
        sink.write(event)

        self.assertEqual(sink.events, (event,))

    def test_metadata_accepts_only_allowlisted_bounded_values(self) -> None:
        item = AuditMetadataItem(AuditMetadataKey.RECORD_ID, "record-123")

        self.assertEqual(audit_event(metadata=(item,)).metadata, (item,))

        with self.assertRaisesRegex(AuditValidationError, "unknown key"):
            AuditMetadataItem("prompt", "private text")  # type: ignore[arg-type]
        with self.assertRaisesRegex(AuditValidationError, "bounded safe label"):
            AuditMetadataItem(
                AuditMetadataKey.RECORD_ID,
                "safe\n{\"forged\":true}",
            )
        with self.assertRaisesRegex(AuditValidationError, "numeric metadata"):
            AuditMetadataItem(AuditMetadataKey.HTTP_STATUS, "404")
        with self.assertRaisesRegex(AuditValidationError, "label metadata"):
            AuditMetadataItem(AuditMetadataKey.RECORD_ID, 123)

    def test_duplicate_metadata_keys_are_rejected(self) -> None:
        item = AuditMetadataItem(AuditMetadataKey.ITEM_COUNT, 2)

        with self.assertRaisesRegex(AuditValidationError, "must be unique"):
            audit_event(metadata=(item, item))

    def test_timestamp_must_be_timezone_aware(self) -> None:
        with self.assertRaisesRegex(AuditValidationError, "timezone"):
            AuditEvent(
                correlation_id=uuid4(),
                component=AuditComponent.APPLICATION,
                operation=AuditOperation.STARTUP,
                outcome=AuditOutcome.SUCCEEDED,
                reason_code=AuditReasonCode.NORMAL,
                timestamp=datetime(2026, 8, 24),
            )

    def test_duration_must_be_non_negative_integer(self) -> None:
        for invalid_duration in (-1, True, 1.5):
            with self.subTest(invalid_duration=invalid_duration):
                with self.assertRaisesRegex(AuditValidationError, "duration"):
                    AuditEvent(
                        correlation_id=uuid4(),
                        component=AuditComponent.MODEL,
                        operation=AuditOperation.MODEL_REQUEST,
                        outcome=AuditOutcome.FAILED,
                        reason_code=AuditReasonCode.MODEL_UNAVAILABLE,
                        duration_ms=invalid_duration,
                    )

    def test_metadata_item_count_is_bounded(self) -> None:
        metadata = tuple(
            AuditMetadataItem(key, "safe")
            for key in (
                AuditMetadataKey.ACTION_KIND,
                AuditMetadataKey.AGENT_ID,
                AuditMetadataKey.APPROVAL_STATE,
                AuditMetadataKey.DESTINATION_CLASS,
                AuditMetadataKey.ERROR_CATEGORY,
                AuditMetadataKey.MODEL_ADAPTER,
                AuditMetadataKey.RECORD_ID,
                AuditMetadataKey.TARGET_CLASS,
                AuditMetadataKey.TASK_ID,
            )
        )

        self.assertEqual(audit_event(metadata=metadata).metadata, metadata)
        repeated_item = AuditMetadataItem(AuditMetadataKey.RECORD_ID, "record-1")
        with self.assertRaisesRegex(AuditValidationError, "too many"):
            audit_event(metadata=(repeated_item,) * 17)

    def test_sink_rejects_an_untyped_event(self) -> None:
        sink = InMemoryAuditSink()

        with self.assertRaisesRegex(AuditValidationError, "typed event"):
            sink.write("not an event")  # type: ignore[arg-type]
