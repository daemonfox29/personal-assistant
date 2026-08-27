"""Current-request search citation provenance tests."""

import json
import unittest

from personal_assistant.search_evidence import (
    evidence_urls_from_tool_content,
    grounded_answer_error,
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


if __name__ == "__main__":
    unittest.main()
