"""Deterministic quality-first search routing tests."""

import unittest

from personal_assistant.search_policy import (
    QualitySearchPolicy,
    SearchPolicyError,
    SearchSource,
    requests_quality_search,
    requests_search_verification,
    strip_explicit_provider_language,
)


class SearchPolicyTests(unittest.TestCase):
    def test_quality_default_routes_general_research_health_and_reference(self) -> None:
        policy = QualitySearchPolicy()

        self.assertEqual(
            policy.plan_for("What happened in Iran today?").sources,
            (SearchSource.GOOGLE,),
        )
        self.assertEqual(
            policy.plan_for("Find peer-reviewed research on sleep.").sources,
            (
                SearchSource.GOOGLE_SCHOLAR,
                SearchSource.OPENALEX,
                SearchSource.SEMANTIC_SCHOLAR,
            ),
        )
        self.assertEqual(
            policy.plan_for("What clinical evidence exists for this treatment?").sources,
            (SearchSource.PUBMED, SearchSource.GOOGLE_SCHOLAR),
        )
        self.assertEqual(
            policy.plan_for("Give me an encyclopedia background on Saturn.").sources,
            (SearchSource.WIKIPEDIA, SearchSource.ENCYCLOPEDIA_COM),
        )

    def test_explicit_enabled_provider_is_the_only_source(self) -> None:
        policy = QualitySearchPolicy()

        plan = policy.plan_for("Only search Google Scholar for synthetic evidence.")

        self.assertTrue(plan.explicit)
        self.assertEqual(plan.sources, (SearchSource.GOOGLE_SCHOLAR,))

    def test_natural_provider_phrases_select_exactly_that_source(self) -> None:
        policy = QualitySearchPolicy(tuple(SearchSource))
        cases = (
            (
                "Check Google Scholar search for info on sleep.",
                SearchSource.GOOGLE_SCHOLAR,
            ),
            ("Check Google search for info on Iran.", SearchSource.GOOGLE),
            ("Use Crossref to find papers on sleep.", SearchSource.CROSSREF),
            ("Look it up with PubMed.", SearchSource.PUBMED),
            (
                "Look up some stuff about bipolar disorder on PubMed, and "
                "put some high-level information together.",
                SearchSource.PUBMED,
            ),
            ("Search Wikipedia for Saturn.", SearchSource.WIKIPEDIA),
        )
        for prompt, expected in cases:
            with self.subTest(prompt=prompt):
                plan = policy.plan_for(prompt)
                self.assertTrue(plan.explicit)
                self.assertEqual(plan.sources, (expected,))

    def test_explicit_disabled_provider_fails_without_fallback(self) -> None:
        policy = QualitySearchPolicy((SearchSource.GOOGLE,))

        with self.assertRaises(SearchPolicyError):
            policy.plan_for("Check Google Scholar for synthetic evidence.")

    def test_provider_override_does_not_persist_into_follow_up(self) -> None:
        policy = QualitySearchPolicy()

        first = policy.plan_for(
            "Look up bipolar disorder on PubMed and summarize it."
        )
        follow_up = policy.plan_for(
            "Is lamotrigine a typical treatment for it? What does it do?"
        )

        self.assertTrue(first.explicit)
        self.assertEqual(first.sources, (SearchSource.PUBMED,))
        self.assertFalse(follow_up.explicit)
        self.assertEqual(
            follow_up.sources,
            (SearchSource.PUBMED, SearchSource.GOOGLE_SCHOLAR),
        )

    def test_provider_language_can_be_removed_without_removing_the_topic(self) -> None:
        cases = (
            (
                "Look up bipolar disorder on PubMed and summarize it.",
                "Look up bipolar disorder and summarize it.",
            ),
            (
                "Only search Google Scholar for sleep research.",
                "sleep research.",
            ),
            (
                "Use Crossref to find papers about sleep.",
                "papers about sleep.",
            ),
        )
        for prompt, expected in cases:
            with self.subTest(prompt=prompt):
                self.assertEqual(strip_explicit_provider_language(prompt), expected)

    def test_owner_enabled_subset_is_respected(self) -> None:
        policy = QualitySearchPolicy(
            (SearchSource.CROSSREF, SearchSource.ARXIV)
        )

        self.assertEqual(
            policy.plan_for("Find scholarly papers about synthetic data.").sources,
            (SearchSource.CROSSREF, SearchSource.ARXIV),
        )

    def test_clear_quality_requests_trigger_deterministic_search(self) -> None:
        self.assertTrue(requests_quality_search("Check Google for current events."))
        self.assertTrue(requests_quality_search("Find peer-reviewed sleep studies."))
        self.assertTrue(requests_quality_search("Give me a Wikipedia overview."))
        self.assertFalse(requests_quality_search("Tell me a joke."))

    def test_personal_context_stays_local_without_an_explicit_search_command(self) -> None:
        self.assertFalse(requests_quality_search("What do you remember about my health?"))
        self.assertFalse(requests_quality_search("Have I told you about my diagnosis?"))
        self.assertFalse(requests_quality_search("What medications did I tell you I take?"))
        with self.assertRaises(SearchPolicyError):
            QualitySearchPolicy().plan_for(
                "What medications did I tell you I take?"
            )
        self.assertTrue(
            requests_quality_search(
                "Only search PubMed for research about my condition."
            )
        )

    def test_second_pass_requires_explicit_owner_wording(self) -> None:
        self.assertTrue(requests_search_verification("Double-check those sources."))
        self.assertTrue(requests_search_verification("Please verify this."))
        self.assertTrue(requests_search_verification("Check your work."))
        self.assertTrue(requests_search_verification("Cross-check the result."))
        self.assertTrue(requests_search_verification("Check that carefully."))
        self.assertFalse(requests_search_verification("Tell me the latest update."))


if __name__ == "__main__":
    unittest.main()
