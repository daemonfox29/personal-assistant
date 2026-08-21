"""Checks for the command-line chat interface."""

import unittest
from unittest.mock import Mock

from personal_assistant.chat import ChatSession
from personal_assistant.model import ModelResponse


class ChatSessionTests(unittest.TestCase):
    """Verify input is sent to the model and exit remains local."""

    def test_message_is_sent_to_the_model_and_answer_is_displayed(self) -> None:
        model = Mock()
        model.generate.return_value = ModelResponse(text="Hello back")
        read_input = Mock(side_effect=["Hello", "quit"])
        write_output = Mock()

        ChatSession(
            model,
            read_input=read_input,
            write_output=write_output,
        ).run()

        self.assertEqual(model.generate.call_args.args[0].prompt, "Hello")
        write_output.assert_any_call("Assistant: Hello back")
        write_output.assert_called_with("Goodbye.")

    def test_empty_message_is_not_sent_to_the_model(self) -> None:
        model = Mock()
        read_input = Mock(side_effect=["   ", "exit"])
        write_output = Mock()

        ChatSession(
            model,
            read_input=read_input,
            write_output=write_output,
        ).run()

        model.generate.assert_not_called()
        write_output.assert_called_with("Goodbye.")

    def test_end_of_input_closes_the_chat(self) -> None:
        read_input = Mock(side_effect=EOFError)
        write_output = Mock()

        ChatSession(
            Mock(),
            read_input=read_input,
            write_output=write_output,
        ).run()

        write_output.assert_called_with("Goodbye.")
