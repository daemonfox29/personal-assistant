"""Checks for safe rendering of untrusted terminal text."""

import unittest

from personal_assistant.terminal_output import sanitize_terminal_text


class TerminalOutputTests(unittest.TestCase):
    def test_plain_text_newlines_and_tabs_are_preserved(self) -> None:
        self.assertEqual(sanitize_terminal_text("Hello\n\tworld"), "Hello\n\tworld")

    def test_terminal_escape_and_bell_are_exposed_not_executed(self) -> None:
        self.assertEqual(
            sanitize_terminal_text("safe\x1b]0;forged\x07text"),
            "safe\\u001b]0;forged\\u0007text",
        )

    def test_invisible_unicode_channels_are_exposed(self) -> None:
        self.assertEqual(
            sanitize_terminal_text("a\u200bb\ufe0f"),
            "a\\u200bb\\ufe0f",
        )
