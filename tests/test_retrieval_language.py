"""Deterministic shared retrieval-language tests."""

import unittest

from personal_assistant.retrieval_language import (
    connected_topic_terms,
    normalized_terms,
    safe_topic_labels,
)


class RetrievalLanguageTests(unittest.TestCase):
    def test_shared_normalization_handles_reviewed_plural_inflections(self) -> None:
        self.assertEqual(
            normalized_terms("sensitivities allergies pets dog's cat’s"),
            ("sensitivity", "allergy", "pet", "dog", "cat"),
        )

    def test_topic_expansion_is_bounded_and_deterministic(self) -> None:
        self.assertEqual(
            connected_topic_terms(("gut", "sensitivity"), maximum_terms=12),
            (
                "gut",
                "sensitivity",
                "digestive",
                "digestion",
                "gluten",
                "celiac",
                "intolerance",
                "allergy",
                "allergic",
            ),
        )

    def test_ui_topics_use_only_reviewed_generic_labels(self) -> None:
        private_value = "I have a synthetic gluten sensitivity named secretvalue."

        labels = safe_topic_labels(private_value, fallback="personal fact")

        self.assertEqual(labels, ("digestive health", "sensitivity or allergy"))
        self.assertNotIn("secretvalue", repr(labels))


if __name__ == "__main__":
    unittest.main()
