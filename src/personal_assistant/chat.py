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

            if not prompt.strip():
                continue

            request = ModelRequest(prompt=prompt)
            if isinstance(self._model, StreamingLanguageModel):
                self._stream_response(request)
            else:
                response = self._model.generate(request)
                self._write_output(f"Assistant: {response.text}")

    def _stream_response(self, request: ModelRequest) -> None:
        self._write_chunk("Assistant: ")
        for text in self._model.stream_generate(request):
            self._write_chunk(text)
        self._write_chunk("\n")

    def _say_goodbye(self) -> None:
        self._write_output("Goodbye.")
