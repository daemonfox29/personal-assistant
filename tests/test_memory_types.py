"""Validation tests for typed persistent-memory values."""

from datetime import datetime, timezone
import unittest
from uuid import uuid4

from personal_assistant.memory_types import (
    ActorType,
    EventPayload,
    FactPayload,
    InsightConfidence,
    InsightPayload,
    MemoryValidationError,
    MentionPolicy,
    NotePayload,
    PolicyPreferencePayload,
    PreferencePayload,
    Provenance,
    Scope,
    ScopeType,
    SourceType,
    canonical_json,
    normalize_alias,
    payload_from_data,
    payload_to_data,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class MemoryTypeTests(unittest.TestCase):
    def test_registered_payloads_round_trip_through_bounded_json(self) -> None:
        payloads = (
            FactPayload("synthetic subject", "synthetic statement"),
            PreferencePayload("synthetic topic", "synthetic preference"),
            EventPayload("synthetic event", NOW),
            NotePayload("synthetic title", "synthetic body"),
            InsightPayload(
                "synthetic observation",
                InsightConfidence.LOW,
                "synthetic contradiction review",
                NOW,
                NOW,
            ),
            PolicyPreferencePayload(
                "synthetic topic",
                MentionPolicy.ASK_BEFORE_MENTIONING,
            ),
        )

        for payload in payloads:
            data = payload_to_data(payload)
            self.assertEqual(payload_from_data(data), payload)
            self.assertLess(len(canonical_json(data).encode("utf-8")), 16_384)

    def test_credential_related_content_is_rejected(self) -> None:
        prohibited = (
            "my password is synthetic",
            "API key abc123",
            "wallet seed phrase synthetic words",
            "credit card number 0000",
            "PIN 1234",
        )

        for value in prohibited:
            with self.assertRaisesRegex(
                MemoryValidationError,
                "Credential-related",
            ):
                FactPayload("synthetic", value)

    def test_hidden_direction_and_control_characters_are_rejected(self) -> None:
        for value in ("safe\u202eevil", "safe\x00evil"):
            with self.assertRaisesRegex(MemoryValidationError, "unsafe"):
                NotePayload("synthetic", value)

    def test_oversized_payload_field_is_rejected(self) -> None:
        with self.assertRaisesRegex(MemoryValidationError, "too large"):
            NotePayload("synthetic", "x" * 8_001)

    def test_scope_requires_the_correct_opaque_identifier_shape(self) -> None:
        self.assertEqual(Scope(ScopeType.GLOBAL).id, None)
        self.assertIsInstance(Scope(ScopeType.PROJECT, uuid4()).id, type(uuid4()))

        with self.assertRaises(MemoryValidationError):
            Scope(ScopeType.GLOBAL, uuid4())
        with self.assertRaises(MemoryValidationError):
            Scope(ScopeType.TOPIC)

    def test_model_provenance_requires_model_actor_and_version(self) -> None:
        provenance = Provenance(
            SourceType.MODEL_CANDIDATE,
            "synthetic-turn",
            ActorType.MODEL_CANDIDATE,
            "synthetic-model-v1",
        )
        self.assertEqual(provenance.model_version, "synthetic-model-v1")

        with self.assertRaises(MemoryValidationError):
            Provenance(
                SourceType.MODEL_CANDIDATE,
                "synthetic-turn",
                ActorType.MODEL_CANDIDATE,
            )
        with self.assertRaises(MemoryValidationError):
            Provenance(
                SourceType.EXPLICIT_USER,
                "synthetic-turn",
                ActorType.USER,
                "false-model-claim",
            )

    def test_alias_normalization_is_exact_and_deterministic(self) -> None:
        self.assertEqual(normalize_alias("  SYNTHETIC   Pet  "), "synthetic pet")

    def test_invalid_insight_range_is_rejected(self) -> None:
        with self.assertRaisesRegex(MemoryValidationError, "time range"):
            InsightPayload(
                "synthetic observation",
                InsightConfidence.LOW,
                "synthetic contradictions",
                datetime(2026, 1, 2, tzinfo=timezone.utc),
                NOW,
            )


if __name__ == "__main__":
    unittest.main()
