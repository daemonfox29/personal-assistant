"""Basic checks that the assistant package can be imported."""


import unittest

from personal_assistant.__main__ import startup_message


class StartupMessageTests(unittest.TestCase):
    def test_startup_message(self) -> None:
        self.assertEqual(startup_message(), "Personal Assistant is ready.")