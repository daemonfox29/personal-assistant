"""A minimal local command-line chat interface."""

from collections.abc import Callable

from personal_assistant.model import LanguageModel, ModelRequest


InputReader = Callable[[str], str]
OutputWriter = Callable[[str], None]
EXIT_COMMANDS = frozenset({"exit", "quit"})


class ChatSession:
    """Run a text conversation using one language-model implementation."""

    def __init__(
        self,
        model: LanguageModel,
        *,
        read_input: InputReader = input,
        write_output: OutputWriter = print,
    ) -> None:
        self._model = model
        self._read_input = read_input
        self._write_output = write_output

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

            response = self._model.generate(ModelRequest(prompt=prompt))
            self._write_output(f"Assistant: {response.text}")

    def _say_goodbye(self) -> None:
        self._write_output("Goodbye.")
