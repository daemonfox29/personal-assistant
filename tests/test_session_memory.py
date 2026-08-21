"""Checks for temporary in-memory conversation context."""

import unittest

from personal_assistant.session_memory import SessionConversationMemory


class SessionConversationMemoryTests(unittest.TestCase):
    """Verify session history is bounded and supplied only with new prompts."""

    def test_first_prompt_has_no_history(self) -> None:
        memory = SessionConversationMemory(character_limit=100)

        self.assertEqual(memory.prompt_with_history("Hello"), "Hello")

    def test_recent_turn_is_included_with_the_next_prompt(self) -> None:
        memory = SessionConversationMemory(character_limit=100)
        memory.add_turn("Tell me about Russia.", "Russia is a country.")

        prompt = memory.prompt_with_history("What about its economy?")

        self.assertIn("Tell me about Russia.", prompt)
        self.assertIn("Russia is a country.", prompt)
        self.assertTrue(prompt.endswith("What about its economy?"))

    def test_history_is_shortened_to_its_character_limit(self) -> None:
        memory = SessionConversationMemory(character_limit=30)
        memory.add_turn("First question", "First answer")
        memory.add_turn("Second question", "Second answer")

        prompt = memory.prompt_with_history("Follow-up")

        self.assertIn("Second answer", prompt)
        self.assertNotIn("First question", prompt)
