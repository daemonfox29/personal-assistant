"""Checks for token-bounded structured conversation context."""

import unittest

from personal_assistant.model import MessageRole, ModelMessage
from personal_assistant.session_memory import (
    ConversationTurn,
    MessageTooLargeError,
    REQUEST_OVERHEAD_TOKENS,
    SessionConversationMemory,
    message_token_count,
)


class SessionConversationMemoryTests(unittest.TestCase):
    """Verify session history stays bounded and preserves trusted roles."""

    def test_first_request_has_separate_system_and_user_messages(self) -> None:
        memory = SessionConversationMemory(token_limit=100)

        messages = memory.messages_for_request(
            system_text="Follow policy.",
            user_text="Hello",
            input_token_limit=100,
        )

        self.assertEqual(
            messages,
            (
                ModelMessage(MessageRole.SYSTEM, "Follow policy."),
                ModelMessage(MessageRole.USER, "Hello"),
            ),
        )

    def test_recent_turn_is_included_as_user_and_assistant_messages(self) -> None:
        memory = SessionConversationMemory(token_limit=200)
        memory.add_turn("Tell me about Russia.", "Russia is a country.")

        messages = memory.messages_for_request(
            system_text="Follow policy.",
            user_text="What about its economy?",
            input_token_limit=200,
        )

        self.assertEqual(
            [message.role for message in messages],
            [
                MessageRole.SYSTEM,
                MessageRole.USER,
                MessageRole.ASSISTANT,
                MessageRole.USER,
            ],
        )
        self.assertEqual(messages[1].content, "Tell me about Russia.")
        self.assertEqual(messages[2].content, "Russia is a country.")
        self.assertEqual(messages[3].content, "What about its economy?")

    def test_ram_budget_evicts_the_oldest_complete_turn(self) -> None:
        second_turn = ConversationTurn("Second question", "Second answer")
        memory = SessionConversationMemory(token_limit=second_turn.token_count())
        memory.add_turn("First question", "First answer")
        memory.add_turn(second_turn.user_text, second_turn.assistant_text)

        messages = memory.messages_for_request(
            system_text="S",
            user_text="Follow-up",
            input_token_limit=200,
        )
        contents = [message.content for message in messages]

        self.assertIn("Second question", contents)
        self.assertIn("Second answer", contents)
        self.assertNotIn("First question", contents)

    def test_request_budget_counts_system_and_current_user_messages(self) -> None:
        memory = SessionConversationMemory(token_limit=200)
        memory.add_turn("Earlier question", "Earlier answer")
        system = ModelMessage(MessageRole.SYSTEM, "System instruction")
        current = ModelMessage(MessageRole.USER, "Current question")
        required_tokens = (
            REQUEST_OVERHEAD_TOKENS
            + message_token_count(system)
            + message_token_count(current)
        )

        messages = memory.messages_for_request(
            system_text=system.content,
            user_text=current.content,
            input_token_limit=required_tokens,
        )

        self.assertEqual(messages, (system, current))

    def test_one_oversized_message_is_rejected_predictably(self) -> None:
        memory = SessionConversationMemory(token_limit=100)
        system = ModelMessage(MessageRole.SYSTEM, "System instruction")
        current = ModelMessage(MessageRole.USER, "Current question")
        required_tokens = (
            REQUEST_OVERHEAD_TOKENS
            + message_token_count(system)
            + message_token_count(current)
        )

        with self.assertRaises(MessageTooLargeError):
            memory.messages_for_request(
                system_text=system.content,
                user_text=current.content,
                input_token_limit=required_tokens - 1,
            )

    def test_turn_larger_than_ram_budget_is_not_stored_partially(self) -> None:
        memory = SessionConversationMemory(token_limit=20)
        memory.add_turn("A long user message", "A long assistant message")

        messages = memory.messages_for_request(
            system_text="S",
            user_text="Now",
            input_token_limit=100,
        )

        self.assertEqual(
            messages,
            (
                ModelMessage(MessageRole.SYSTEM, "S"),
                ModelMessage(MessageRole.USER, "Now"),
            ),
        )
