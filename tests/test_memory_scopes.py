"""Checks for conservative owner-authored contextual-scope recognition."""

import unittest

from personal_assistant.memory_scopes import (
    detect_explicit_named_scope,
    named_scope_needs_clarification,
    normalize_scope_label,
)
from personal_assistant.memory_types import MemoryValidationError, ScopeType


class MemoryScopeLanguageTests(unittest.TestCase):
    def test_explicit_context_phrases_are_typed_without_model_inference(self) -> None:
        place = detect_explicit_named_scope(
            "At work, I prefer quiet time for focused tasks."
        )
        project = detect_explicit_named_scope(
            "For project Apollo, I prefer concise status notes."
        )
        topic = detect_explicit_named_scope(
            "When discussing family plans, I prefer a gentle tone."
        )

        self.assertEqual(place.scope_type, ScopeType.PLACE)  # type: ignore[union-attr]
        self.assertEqual(place.display_label, "work")  # type: ignore[union-attr]
        self.assertEqual(project.scope_type, ScopeType.PROJECT)  # type: ignore[union-attr]
        self.assertEqual(project.display_label, "Apollo")  # type: ignore[union-attr]
        self.assertEqual(topic.scope_type, ScopeType.TOPIC)  # type: ignore[union-attr]
        self.assertEqual(topic.display_label, "family plans")  # type: ignore[union-attr]

    def test_ambiguous_context_without_comma_is_not_scoped(self) -> None:
        text = "I prefer quiet time when I am at work."
        self.assertIsNone(detect_explicit_named_scope(text))
        self.assertTrue(named_scope_needs_clarification(text))

    def test_scope_labels_are_normalized_and_credential_text_is_rejected(self) -> None:
        self.assertEqual(normalize_scope_label("  Family   Plans  "), "family plans")
        with self.assertRaises(MemoryValidationError):
            normalize_scope_label("my password")
