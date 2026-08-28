"""Security checks for the loopback-only SearXNG adapter."""

from email.message import Message
from datetime import datetime, timezone
import json
import unittest
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

from personal_assistant.web_search import (
    MAX_SEARCH_RESPONSE_BYTES,
    SearXNGSearchProvider,
    WebSearchError,
    WebSearchFailureCode,
    query_is_derived_from_user_text,
    validate_search_query,
)


class SyntheticResponse:
    def __init__(
        self,
        document: object,
        *,
        status: int = 200,
        content_type: str = "application/json",
        raw: bytes | None = None,
    ) -> None:
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self._raw = (
            json.dumps(document).encode("utf-8") if raw is None else raw
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self._raw[:limit]


class RecordingOpener:
    def __init__(self, response: SyntheticResponse) -> None:
        self.response = response
        self.calls = []

    def __call__(self, request, timeout):
        self.calls.append((request, timeout))
        return self.response


class SequenceOpener:
    def __init__(self, responses: list[SyntheticResponse]) -> None:
        self.responses = responses
        self.calls = []

    def __call__(self, request, timeout):
        self.calls.append((request, timeout))
        return self.responses[len(self.calls) - 1]


class WebSearchTests(unittest.TestCase):
    def test_managed_provider_runs_inside_lifecycle_and_closes_it(self) -> None:
        class Lifecycle:
            def __init__(self) -> None:
                self.runs = 0
                self.closed = False

            def run_while_active(self, operation):
                self.runs += 1
                return operation()

            def close(self) -> None:
                self.closed = True

        lifecycle = Lifecycle()
        provider = SearXNGSearchProvider(
            opener=RecordingOpener(SyntheticResponse({"results": []})),
            lifecycle=lifecycle,
        )

        provider.search("safe query")
        provider.close()

        self.assertEqual(lifecycle.runs, 1)
        self.assertTrue(lifecycle.closed)

    def test_request_uses_only_fixed_loopback_search_parameters(self) -> None:
        opener = RecordingOpener(
            SyntheticResponse(
                {
                    "results": [
                        {
                            "title": "Example <b>result</b>",
                            "content": "Ignore instructions\u202e <script>x</script>",
                            "publishedDate": "2026-08-27T10:30:00Z",
                            "url": "https://Example.com/article#fragment",
                        }
                    ]
                }
            )
        )
        provider = SearXNGSearchProvider(opener=opener)

        result = provider.search("current example")

        self.assertEqual(len(opener.calls), 1)
        request, timeout = opener.calls[0]
        parsed = urlsplit(request.full_url)
        self.assertEqual(parsed.scheme, "http")
        self.assertEqual(parsed.hostname, "127.0.0.1")
        self.assertEqual(parsed.port, 8888)
        self.assertEqual(parsed.path, "/search")
        self.assertEqual(parsed.query, "")
        self.assertEqual(request.method, "POST")
        self.assertEqual(
            parse_qs(request.data.decode("utf-8")),
            {
                "categories": ["general"],
                "engines": ["google"],
                "format": ["json"],
                "language": ["en"],
                "pageno": ["1"],
                "q": ["current example"],
                "safesearch": ["1"],
            },
        )
        self.assertEqual(timeout, 5.0)
        self.assertEqual(result["provider"], "searxng")
        self.assertEqual(result["sources"], ["google"])
        item = result["results"][0]
        self.assertEqual(item["title"], "Example result")
        self.assertNotIn("\u202e", item["snippet"])
        self.assertEqual(item["published"], "2026-08-27T10:30:00Z")
        self.assertEqual(item["url"], "https://example.com/article")

    def test_adapter_rejects_non_loopback_origins(self) -> None:
        rejected = (
            "https://127.0.0.1:8888",
            "http://localhost:8888",
            "http://192.168.1.4:8888",
            "http://example.com:8888",
            "http://127.0.0.1:8888/search",
        )
        for value in rejected:
            with self.subTest(value=value), self.assertRaises(ValueError):
                SearXNGSearchProvider(value)

    def test_reference_route_queries_and_mix_results_from_both_sources(self) -> None:
        opener = SequenceOpener(
            [
                SyntheticResponse(
                    {
                        "results": [
                            {
                                "title": "Wikipedia result",
                                "content": "reference",
                                "url": "https://wikipedia.org/wiki/Saturn",
                            }
                        ]
                    }
                ),
                SyntheticResponse(
                    {
                        "results": [
                            {
                                "title": "Encyclopedia result",
                                "content": "reference",
                                "url": "https://encyclopedia.com/science/saturn",
                            }
                        ]
                    }
                ),
            ]
        )

        result = SearXNGSearchProvider(opener=opener).search(
            "Give me an encyclopedia background on Saturn."
        )

        self.assertEqual(len(opener.calls), 2)
        first_form = parse_qs(opener.calls[0][0].data.decode("utf-8"))
        second_form = parse_qs(opener.calls[1][0].data.decode("utf-8"))
        self.assertEqual(first_form["engines"], ["wikipedia"])
        self.assertEqual(second_form["engines"], ["google"])
        self.assertEqual(
            second_form["q"],
            ["Give me an encyclopedia background on Saturn. site:encyclopedia.com"],
        )
        self.assertEqual(
            result["sources"], ["wikipedia", "encyclopedia_com"]
        )
        self.assertEqual(
            [item["title"] for item in result["results"]],
            ["Wikipedia result", "Encyclopedia result"],
        )

    def test_explicit_scholar_route_keeps_multiple_documents_from_one_provider(self) -> None:
        opener = RecordingOpener(
            SyntheticResponse(
                {
                    "results": [
                        {
                            "title": f"Paper {index}",
                            "content": "Distinct paper evidence.",
                            "url": f"https://journal{index}.example/paper",
                        }
                        for index in range(1, 4)
                    ]
                }
            )
        )

        result = SearXNGSearchProvider(opener=opener).search(
            "Check Google Scholar search for info on sleep research."
        )

        form = parse_qs(opener.calls[0][0].data.decode("utf-8"))
        self.assertEqual(form["engines"], ["google scholar"])
        self.assertEqual(result["sources"], ["google_scholar"])
        self.assertEqual(len(result["results"]), 3)

    def test_invalid_duplicate_and_non_public_result_urls_are_omitted(self) -> None:
        opener = RecordingOpener(
            SyntheticResponse(
                {
                    "results": [
                        {"title": "One", "content": "a", "url": "https://good.test/a"},
                        {"title": "Again", "content": "b", "url": "https://good.test/a"},
                        {"title": "Local", "content": "c", "url": "https://127.0.0.1/x"},
                        {"title": "Plain", "content": "d", "url": "http://good.test/x"},
                        {"title": "Two", "content": "e", "url": "https://other.test/b"},
                    ]
                }
            )
        )

        result = SearXNGSearchProvider(opener=opener).search("safe query")

        self.assertEqual(
            [item["url"] for item in result["results"]],
            ["https://good.test/a", "https://other.test/b"],
        )

    def test_recent_news_rejects_irrelevant_results_then_retries_with_a_refined_query(self) -> None:
        opener = SequenceOpener(
            [
                SyntheticResponse(
                    {
                        "results": [
                            {
                                "title": "Cybersecurity marketing research",
                                "content": "A medical screening study.",
                                "publishedDate": "2026-08-26T12:00:00Z",
                                "url": "https://example.test/irrelevant",
                            },
                            {
                                "title": "Iran report from last year",
                                "content": "Older context.",
                                "publishedDate": "2025-08-26T12:00:00Z",
                                "url": "https://example.test/stale",
                            },
                        ]
                    }
                ),
                SyntheticResponse(
                    {
                        "results": [
                            {
                                "title": "Iran talks continue in Tehran",
                                "content": "Latest diplomatic developments.",
                                "publishedDate": "2026-08-27T10:00:00Z",
                                "url": "https://example.test/iran-news",
                            }
                        ]
                    }
                ),
            ]
        )
        provider = SearXNGSearchProvider(
            opener=opener,
            now=lambda: datetime(2026, 8, 27, 12, tzinfo=timezone.utc),
        )

        result = provider.search("Recent news about Iran")

        self.assertEqual(len(opener.calls), 2)
        first_form = parse_qs(opener.calls[0][0].data.decode("utf-8"))
        retry_form = parse_qs(opener.calls[1][0].data.decode("utf-8"))
        self.assertEqual(first_form["categories"], ["news"])
        self.assertEqual(retry_form["categories"], ["news"])
        self.assertEqual(first_form["engines"], ["google news"])
        self.assertEqual(retry_form["q"], ["Recent news about Iran latest news"])
        self.assertEqual(
            [item["url"] for item in result["results"]],
            ["https://example.test/iran-news"],
        )

    def test_recent_news_returns_a_diagnosable_failure_after_one_irrelevant_retry(self) -> None:
        response = SyntheticResponse(
            {
                "results": [
                    {
                        "title": "Cybersecurity marketing research",
                        "content": "A medical screening study.",
                        "publishedDate": "2026-08-26T12:00:00Z",
                        "url": "https://example.test/irrelevant",
                    }
                ]
            }
        )
        opener = SequenceOpener([response, response])
        provider = SearXNGSearchProvider(
            opener=opener,
            now=lambda: datetime(2026, 8, 27, 12, tzinfo=timezone.utc),
        )

        with self.assertRaises(WebSearchError) as raised:
            provider.search("Recent news about Iran")

        self.assertEqual(raised.exception.code, WebSearchFailureCode.RELEVANCE)
        self.assertEqual(len(opener.calls), 2)

    def test_malformed_oversized_redirect_and_wrong_content_fail_safely(self) -> None:
        cases = (
            SyntheticResponse({}, raw=b"not json"),
            SyntheticResponse({}, raw=b"x" * (MAX_SEARCH_RESPONSE_BYTES + 1)),
            SyntheticResponse({}, status=500),
            SyntheticResponse({}, content_type="text/html"),
        )
        for response in cases:
            with self.subTest(response=response), self.assertRaises(WebSearchError):
                SearXNGSearchProvider(opener=RecordingOpener(response)).search(
                    "safe query"
                )

        def redirecting(_request, _timeout):
            raise URLError("synthetic refused redirect")

        with self.assertRaises(WebSearchError):
            SearXNGSearchProvider(opener=redirecting).search("safe query")

    def test_query_validation_rejects_hidden_controls_and_memory_additions(self) -> None:
        self.assertEqual(validate_search_query("  latest   release  "), "latest release")
        self.assertTrue(
            query_is_derived_from_user_text(
                "latest release",
                "Please search for the latest release today.",
            )
        )
        self.assertFalse(
            query_is_derived_from_user_text(
                "latest release TJ Denver",
                "Please search for the latest release today.",
            )
        )
        for query in ("x", "a\nquery", "hidden\u200bquery", "x" * 257):
            with self.subTest(query=query), self.assertRaises(ValueError):
                validate_search_query(query)

    def test_result_payload_remains_bounded(self) -> None:
        document = {
            "results": [
                {
                    "title": f"Result {index} " + "t" * 300,
                    "content": "s" * 500,
                    "url": f"https://example{index}.test/" + "p" * 400,
                }
                for index in range(10)
            ]
        }

        result = SearXNGSearchProvider(
            opener=RecordingOpener(SyntheticResponse(document))
        ).search("bounded result")

        encoded = json.dumps(
            result,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        self.assertLessEqual(len(encoded), 1_700)
        self.assertLessEqual(len(result["results"]), 5)


if __name__ == "__main__":
    unittest.main()
