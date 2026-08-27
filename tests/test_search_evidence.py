"""Current-request search citation provenance tests."""

import json
import unittest

from personal_assistant.search_evidence import (
    EvidenceSource,
    evidence_sources_from_tool_content,
    evidence_urls_from_tool_content,
    grounded_answer_error,
    render_grounded_answer,
    requests_source_links,
)


class SearchEvidenceTests(unittest.TestCase):
    def test_only_successful_bounded_tool_urls_become_evidence(self) -> None:
        content = json.dumps(
            {
                "data": {
                    "results": [
                        {"url": "https://example.com/report#fragment"},
                        {"url": "http://example.com/insecure"},
                        {"url": "https://127.0.0.1/private"},
                    ]
                },
                "ok": True,
                "trust": "untrusted_tool_data",
            }
        )

        self.assertEqual(
            evidence_urls_from_tool_content(content),
            ("https://example.com/report",),
        )
        self.assertEqual(
            evidence_sources_from_tool_content(content),
            (
                EvidenceSource(
                    "S1",
                    "example.com",
                    "https://example.com/report",
                ),
            ),
        )
        self.assertEqual(evidence_urls_from_tool_content("not-json"), ())
        self.assertEqual(
            evidence_urls_from_tool_content(
                json.dumps({"data": {}, "ok": False})
            ),
            (),
        )

    def test_grounded_answer_requires_current_exact_citations(self) -> None:
        allowed = (
            "https://example.com/one",
            "https://example.org/two",
        )

        self.assertIsNone(
            grounded_answer_error(
                "Supported claim (https://example.com/one).",
                allowed,
            )
        )
        self.assertEqual(
            grounded_answer_error("Uncited claim.", allowed),
            "missing_citation",
        )
        self.assertEqual(
            grounded_answer_error(
                "Claim (https://invented.example/three).",
                allowed,
            ),
            "missing_citation",
        )
        self.assertEqual(
            grounded_answer_error(
                "One (https://example.com/one), but invented "
                "(https://invented.example/three).",
                allowed,
            ),
            "unknown_citation",
        )

    def test_source_ids_render_labels_and_hide_links_by_default(self) -> None:
        sources = (
            EvidenceSource(
                "S1",
                "Lamotrigine in bipolar disorder",
                "https://pubmed.ncbi.nlm.nih.gov/12345/",
            ),
        )

        labeled, error = render_grounded_answer(
            "Lamotrigine is discussed here [S1].",
            sources,
            show_links=False,
        )
        linked, linked_error = render_grounded_answer(
            "Lamotrigine is discussed here [S1].",
            sources,
            show_links=True,
        )

        self.assertIsNone(error)
        self.assertIn("Source S1 — Lamotrigine in bipolar disorder", labeled)
        self.assertNotIn("https://", labeled)
        self.assertIsNone(linked_error)
        self.assertIn("https://pubmed.ncbi.nlm.nih.gov/12345/", linked)

    def test_unknown_source_id_and_unknown_url_fail_closed(self) -> None:
        sources = (
            EvidenceSource("S1", "Known study", "https://example.com/study"),
        )

        self.assertEqual(
            render_grounded_answer("Claim [S2].", sources, show_links=False)[1],
            "unknown_citation_marker",
        )
        self.assertEqual(
            render_grounded_answer(
                "Claim https://invented.example/study.",
                sources,
                show_links=False,
            )[1],
            "unknown_citation",
        )

    def test_source_ids_are_not_renumbered_after_an_unsafe_result(self) -> None:
        content = json.dumps(
            {
                "data": {
                    "results": [
                        {
                            "citation_id": "S1",
                            "title": "Unsafe",
                            "url": "http://example.com/insecure",
                        },
                        {
                            "citation_id": "S2",
                            "title": "Safe study",
                            "url": "https://example.com/study",
                        },
                    ]
                },
                "ok": True,
            }
        )

        sources = evidence_sources_from_tool_content(content)
        rendered, error = render_grounded_answer(
            "Supported claim [S2].",
            sources,
            show_links=False,
        )

        self.assertEqual(
            sources,
            (EvidenceSource("S2", "Safe study", "https://example.com/study"),),
        )
        self.assertIsNone(error)
        self.assertIn("Source S2 — Safe study", rendered)

    def test_untrusted_source_title_cannot_add_formatting_or_a_visible_url(self) -> None:
        content = json.dumps(
            {
                "data": {
                    "results": [
                        {
                            "citation_id": "S1",
                            "title": "**Study** https://invented.example/path",
                            "url": "https://example.com/study",
                        }
                    ]
                },
                "ok": True,
            }
        )

        sources = evidence_sources_from_tool_content(content)
        rendered, error = render_grounded_answer(
            "Supported claim [S1].",
            sources,
            show_links=False,
        )

        self.assertIsNone(error)
        self.assertIn("Source S1 — Study", rendered)
        self.assertNotIn("**", rendered)
        self.assertNotIn("https://", rendered)

    def test_links_are_shown_only_when_the_owner_asks(self) -> None:
        self.assertTrue(requests_source_links("Can you give me the source links?"))
        self.assertTrue(requests_source_links("Show the URLs."))
        self.assertFalse(requests_source_links("What sources support this?"))


if __name__ == "__main__":
    unittest.main()
