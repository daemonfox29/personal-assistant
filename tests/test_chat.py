"""Checks for the command-line chat interface."""

import unittest
from unittest.mock import Mock

from personal_assistant.chat import ChatSession
from personal_assistant.model import ModelResponse, ModelStreamChunk


class StreamingTestModel:
    """A tiny model that returns two response chunks for a chat test."""

    def generate(self, request):
        raise AssertionError("The streaming path should be used instead.")

    def stream_generate(self, request):
        yield ModelStreamChunk(text="Hello")
        yield ModelStreamChunk(text=" back")


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

    def test_streaming_model_displays_each_response_piece_immediately(self) -> None:
        chunks: list[str] = []
        read_input = Mock(side_effect=["Hello", "quit"])
        write_output = Mock()

        ChatSession(
            StreamingTestModel(),
            read_input=read_input,
            write_output=write_output,
            write_chunk=chunks.append,
        ).run()

        self.assertEqual(chunks, ["Assistant: ", "Hello", " back", "\n"])
        write_output.assert_called_with("Goodbye.")

    def test_long_command_removes_the_default_response_cap(self) -> None:
        model = Mock()
        model.generate.return_value = ModelResponse(text="Long reply")
        read_input = Mock(side_effect=["/long Explain the history", "quit"])

        ChatSession(model, read_input=read_input, write_output=Mock()).run()

        request = model.generate.call_args.args[0]
        self.assertEqual(request.prompt, "Explain the history")
        self.assertEqual(request.max_response_tokens, -1)

    def test_limit_notice_is_shown_when_streaming_hits_its_cap(self) -> None:
        class LimitedStreamingModel:
            def generate(self, request):
                raise AssertionError("The streaming path should be used instead.")

            def stream_generate(self, request):
                yield ModelStreamChunk(text="Partial", done_reason="length")

        write_output = Mock()
        ChatSession(
            LimitedStreamingModel(),
            read_input=Mock(side_effect=["Hello", "quit"]),
            write_output=write_output,
            write_chunk=Mock(),
        ).run()

        write_output.assert_any_call(
            "[Response stopped at its token limit. Use '/long <question>' "
            "to allow a longer answer.]"
        )

    def test_end_of_input_closes_the_chat(self) -> None:
        read_input = Mock(side_effect=EOFError)
        write_output = Mock()

        ChatSession(
            Mock(),
            read_input=read_input,
            write_output=write_output,
        ).run()

        write_output.assert_called_with("Goodbye.")
