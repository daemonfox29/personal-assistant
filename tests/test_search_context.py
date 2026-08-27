"""Conversational public-search query resolution tests."""

import unittest

from personal_assistant.search_context import resolve_search_query
from personal_assistant.search_policy import QualitySearchPolicy, SearchSource


class SearchContextTests(unittest.TestCase):
    def test_resolves_people_products_and_topics_without_domain_rules(self) -> None:
        cases = (
            (
                "Can you give me some popular books on her?",
                ("Tell me about Janis Joplin.",),
                "Can you give me some popular books on Janis Joplin?",
            ),
            (
                "Where can I buy it?",
                ("Explain the Celestron StarSense Explorer.",),
                "Where can I buy Celestron StarSense Explorer?",
            ),
            (
                "What are some books about it?",
                ("What was the French Revolution?",),
                "What are some books about French Revolution?",
            ),
            (
                "What about its release history?",
                ("Research the Django web framework.",),
                "Django web framework release history",
            ),
        )
        for current, prior, expected in cases:
            with self.subTest(current=current):
                resolution = resolve_search_query(current, prior)
                self.assertEqual(resolution.query, expected)
                self.assertTrue(resolution.used_prior_user_context)

    def test_standalone_query_is_unchanged(self) -> None:
        resolution = resolve_search_query(
            "Popular books about Janis Joplin",
            ("Tell me about Nina Simone.",),
        )

        self.assertEqual(resolution.query, "Popular books about Janis Joplin")
        self.assertFalse(resolution.used_prior_user_context)

    def test_current_explicit_topic_is_never_replaced_by_an_older_topic(self) -> None:
        resolution = resolve_search_query(
            "Compare Madonna and her most influential albums.",
            ("Tell me about Janis Joplin.",),
        )

        self.assertEqual(
            resolution.query,
            "Compare Madonna and her most influential albums.",
        )
        self.assertFalse(resolution.used_prior_user_context)

    def test_prior_provider_command_supplies_topic_but_never_provider_scope(self) -> None:
        resolution = resolve_search_query(
            "Is lamotrigine a typical treatment for it?",
            ("Look up bipolar disorder on PubMed and summarize it.",),
        )

        self.assertEqual(
            resolution.query,
            "Is lamotrigine a typical treatment for bipolar disorder?",
        )
        plan = QualitySearchPolicy().plan_for(resolution.query or "")
        self.assertFalse(plan.explicit)
        self.assertEqual(
            plan.sources,
            (SearchSource.PUBMED, SearchSource.GOOGLE_SCHOLAR),
        )

    def test_unresolved_or_sensitive_reference_requires_clarification(self) -> None:
        for prior in (
            (),
            ("My passphrase is synthetic-secret.",),
            ("Email me at person@example.test.",),
            ("Jane Doe is my therapist.",),
            ("I live near the Celestron store.",),
        ):
            with self.subTest(prior=prior):
                self.assertIsNone(resolve_search_query("Search for it.", prior).query)

    def test_only_recent_user_text_can_supply_the_topic(self) -> None:
        resolution = resolve_search_query(
            "Can you find books about her?",
            ("Thanks.",),
        )

        self.assertIsNone(resolution.query)


if __name__ == "__main__":
    unittest.main()
