"""A minimal local command-line chat interface."""

from collections.abc import Callable

from personal_assistant.model import (
    LanguageModel,
    ModelRequest,
    StreamingLanguageModel,
)
from personal_assistant.config import ChatSettings
from personal_assistant.session_memory import SessionConversationMemory


InputReader = Callable[[str], str]
OutputWriter = Callable[[str], None]
ChunkWriter = Callable[[str], None]
PreparedRequest = tuple[ModelRequest, str]
EXIT_COMMANDS = frozenset({"exit", "quit"})
LONG_RESPONSE_COMMAND = "/long"
MAX_RESPONSE_COMMAND = "/max"
CUSTOM_LIMIT_COMMAND = "/limit"


def _write_chunk(text: str) -> None:
    """Display text immediately without inserting a line after every chunk."""

    print(text, end="", flush=True)


class ChatSession:
    """Run a text conversation using one language-model implementation."""

    def __init__(
        self,
        model: LanguageModel,
        settings: ChatSettings = ChatSettings(),
        *,
        read_input: InputReader = input,
        write_output: OutputWriter = print,
        write_chunk: ChunkWriter = _write_chunk,
    ) -> None:
        self._model = model
        self._read_input = read_input
        self._write_output = write_output
        self._write_chunk = write_chunk
        self._settings = settings
        self._memory = SessionConversationMemory(
            settings.session_history_characters
        )

    def run(self) -> None:
        """Continue chatting until the user exits or closes the terminal."""

        self._write_output(
            "Type 'quit' or 'exit' to close. Use '/long <question>' for a "
            f"{self._settings.long_response_tokens:,}-token answer, "
            f"'/max <question>' for {self._settings.maximum_response_tokens:,} "
            "tokens, or '/limit <1-"
            f"{self._settings.maximum_response_tokens}> <question>' for a "
            "custom limit."
        )

        while True:
            try:
                prompt = self._read_input("You: ")
            except EOFError:
                self._say_goodbye()
                return

            if prompt.strip().lower() in EXIT_COMMANDS:
                self._say_goodbye()
                return

            prepared_request = self._request_from_prompt(prompt)
            if prepared_request is None:
                continue
            request, user_text = prepared_request

            if isinstance(self._model, StreamingLanguageModel):
                response_text = self._stream_response(request)
            else:
                response = self._model.generate(request)
                self._write_output(f"Assistant: {response.text}")
                response_text = response.text

            self._memory.add_turn(user_text, response_text)

    def _stream_response(self, request: ModelRequest) -> str:
        self._write_chunk("Assistant: ")
        limit_reached = False
        response_pieces: list[str] = []
        for chunk in self._model.stream_generate(request):
            self._write_chunk(chunk.text)
            response_pieces.append(chunk.text)
            limit_reached = limit_reached or chunk.done_reason == "length"
        self._write_chunk("\n")
        if limit_reached:
            self._write_output(
                "[Response stopped at its token limit. Use '/long <question>' "
                "or '/max <question>' for a longer answer.]"
            )
        return "".join(response_pieces)

    def _long_request(
        self,
        separator: str,
        remaining_prompt: str,
    ) -> PreparedRequest | None:
        if not separator or not remaining_prompt.strip():
            self._write_output("Usage: /long <question>")
            return None

        return self._prepared_request(
            remaining_prompt.strip(),
            max_response_tokens=self._settings.long_response_tokens,
        )

    def _max_request(
        self,
        separator: str,
        remaining_prompt: str,
    ) -> PreparedRequest | None:
        if not separator or not remaining_prompt.strip():
            self._write_output("Usage: /max <question>")
            return None

        return self._prepared_request(
            remaining_prompt.strip(),
            max_response_tokens=self._settings.maximum_response_tokens,
        )

    def _custom_limit_request(
        self,
        separator: str,
        remaining_prompt: str,
    ) -> PreparedRequest | None:
        if not separator:
            self._write_output(
                "Usage: /limit <1-"
                f"{self._settings.maximum_response_tokens}> <question>"
            )
            return None

        token_limit, question_separator, question = remaining_prompt.partition(" ")
        if not question_separator or not question.strip():
            self._write_output(
                "Usage: /limit <1-"
                f"{self._settings.maximum_response_tokens}> <question>"
            )
            return None

        try:
            response_limit = int(token_limit)
        except ValueError:
            self._write_output("The /limit token limit must be a whole number.")
            return None

        if not 1 <= response_limit <= self._settings.maximum_response_tokens:
            self._write_output(
                "The /limit token limit must be between 1 and "
                f"{self._settings.maximum_response_tokens}."
            )
            return None

        return self._prepared_request(
            question.strip(),
            max_response_tokens=response_limit,
        )

    def _request_from_prompt(self, prompt: str) -> PreparedRequest | None:
        """Return a request, or ignore blank input and incomplete commands."""

        stripped_prompt = prompt.strip()
        if not stripped_prompt:
            return None

        command, separator, remaining_prompt = stripped_prompt.partition(" ")
        if command.lower() not in {
            LONG_RESPONSE_COMMAND,
            MAX_RESPONSE_COMMAND,
            CUSTOM_LIMIT_COMMAND,
        }:
            return self._prepared_request(prompt)

        if command.lower() == LONG_RESPONSE_COMMAND:
            return self._long_request(separator, remaining_prompt)
        if command.lower() == MAX_RESPONSE_COMMAND:
            return self._max_request(separator, remaining_prompt)
        return self._custom_limit_request(separator, remaining_prompt)

    def _prepared_request(
        self,
        user_text: str,
        *,
        max_response_tokens: int | None = None,
    ) -> PreparedRequest:
        return (
            ModelRequest(
                prompt=self._memory.prompt_with_history(user_text),
                max_response_tokens=max_response_tokens,
            ),
            user_text,
        )

    def _say_goodbye(self) -> None:
        self._write_output("Goodbye.")
