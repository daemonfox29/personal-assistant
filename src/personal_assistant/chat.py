"""A minimal local command-line chat interface."""

from collections.abc import Callable

from personal_assistant.model import (
    LanguageModel,
    ModelRequest,
    StreamingLanguageModel,
)


InputReader = Callable[[str], str]
OutputWriter = Callable[[str], None]
ChunkWriter = Callable[[str], None]
EXIT_COMMANDS = frozenset({"exit", "quit"})
LONG_RESPONSE_COMMAND = "/long"


def _write_chunk(text: str) -> None:
    """Display text immediately without inserting a line after every chunk."""

    print(text, end="", flush=True)


class ChatSession:
    """Run a text conversation using one language-model implementation."""

    def __init__(
        self,
        model: LanguageModel,
        *,
        read_input: InputReader = input,
        write_output: OutputWriter = print,
        write_chunk: ChunkWriter = _write_chunk,
    ) -> None:
        self._model = model
        self._read_input = read_input
        self._write_output = write_output
        self._write_chunk = write_chunk

    def run(self) -> None:
        """Continue chatting until the user exits or closes the terminal."""

        self._write_output("Type 'quit' or 'exit' to close the assistant.")

        while True:
            try:
                prompt = self._read_input("You: ")
            except EOFError:
                self._say_goodbye()
                return

            if prompt.strip().lower() in EXIT_COMMANDS:
                self._say_goodbye()
                return

            request = self._request_from_prompt(prompt)
            if request is None:
                continue

            if isinstance(self._model, StreamingLanguageModel):
                self._stream_response(request)
            else:
                response = self._model.generate(request)
                self._write_output(f"Assistant: {response.text}")

    def _stream_response(self, request: ModelRequest) -> None:
        self._write_chunk("Assistant: ")
        limit_reached = False
        for chunk in self._model.stream_generate(request):
            self._write_chunk(chunk.text)
            limit_reached = limit_reached or chunk.done_reason == "length"
        self._write_chunk("\n")
        if limit_reached:
            self._write_output(
                "[Response stopped at its token limit. Use '/long <question>' "
                "to allow a longer answer.]"
            )

    def _request_from_prompt(self, prompt: str) -> ModelRequest | None:
        """Return a request, or ignore blank input and incomplete commands."""

        stripped_prompt = prompt.strip()
        if not stripped_prompt:
            return None

        command, separator, long_prompt = stripped_prompt.partition(" ")
        if command.lower() != LONG_RESPONSE_COMMAND:
            return ModelRequest(prompt=prompt)

        if not separator or not long_prompt.strip():
            self._write_output("Usage: /long <question>")
            return None

        return ModelRequest(
            prompt=long_prompt.strip(),
            max_response_tokens=-1,
        )

    def _say_goodbye(self) -> None:
        self._write_output("Goodbye.")
