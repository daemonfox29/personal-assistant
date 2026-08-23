"""Checks for the HTTP boundary used by local-only model adapters."""

import os
import unittest
from unittest.mock import patch
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request

from personal_assistant.local_http import (
    LocalConnectionError,
    NoRedirectHandler,
    build_local_only_opener,
    open_local,
    validate_loopback_http_url,
)


class LocalHttpTests(unittest.TestCase):
    """Verify that local HTTP cannot escape the machine through URL features."""

    def test_ipv4_loopback_base_url_is_accepted(self) -> None:
        self.assertEqual(
            validate_loopback_http_url(
                "http://127.0.0.1:11434/",
                base_url=True,
            ),
            "http://127.0.0.1:11434",
        )

    def test_ipv6_loopback_base_url_is_accepted(self) -> None:
        self.assertEqual(
            validate_loopback_http_url(
                "http://[::1]:11434",
                base_url=True,
            ),
            "http://[::1]:11434",
        )

    def test_non_loopback_and_hostname_urls_are_rejected(self) -> None:
        rejected_urls = (
            "http://localhost:11434",
            "http://192.168.1.2:11434",
            "http://0.0.0.0:11434",
            "http://example.com:11434",
        )

        for url in rejected_urls:
            with self.subTest(url=url), self.assertRaises(LocalConnectionError):
                validate_loopback_http_url(url, base_url=True)

    def test_unsafe_url_features_are_rejected(self) -> None:
        rejected_urls = (
            "https://127.0.0.1:11434",
            "http://user:password@127.0.0.1:11434",
            "http://127.0.0.1",
            "http://127.0.0.1:0",
            "http://127.0.0.1:11434/remote/path",
            "http://127.0.0.1:11434?target=remote",
            "http://127.0.0.1:11434#fragment",
        )

        for url in rejected_urls:
            with self.subTest(url=url), self.assertRaises(LocalConnectionError):
                validate_loopback_http_url(url, base_url=True)

    def test_request_is_validated_before_the_opener_is_called(self) -> None:
        request = Request("http://example.com:11434/api/tags")

        with patch(
            "personal_assistant.local_http._LOCAL_ONLY_OPENER.open"
        ) as opener:
            with self.assertRaises(LocalConnectionError):
                open_local(request, 1.0)

        opener.assert_not_called()

    def test_local_opener_ignores_environment_proxies(self) -> None:
        with (
            patch.dict(
                os.environ,
                {"HTTP_PROXY": "http://proxy.example:8080"},
            ),
            patch("urllib.request.getproxies") as get_proxies,
        ):
            opener = build_local_only_opener()

        get_proxies.assert_not_called()
        self.assertFalse(
            any(isinstance(handler, ProxyHandler) for handler in opener.handlers)
        )

    def test_local_opener_refuses_redirects(self) -> None:
        opener = build_local_only_opener()
        redirect_handlers = [
            handler
            for handler in opener.handlers
            if isinstance(handler, HTTPRedirectHandler)
        ]

        self.assertEqual(len(redirect_handlers), 1)
        self.assertIsInstance(redirect_handlers[0], NoRedirectHandler)
        self.assertIsNone(
            redirect_handlers[0].redirect_request(
                None,
                None,
                302,
                "Found",
                {},
                "http://127.0.0.1:9999/redirected",
            )
        )
