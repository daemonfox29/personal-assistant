"""Command-line entry point for the Personal Assistant."""

from personal_assistant.chat import ChatSession
from personal_assistant.config import load_settings
from personal_assistant.ollama_adapter import OllamaModel


def startup_message() -> str:
    """Return the assistant's initial status message."""
    return "Personal Assistant is ready."


def main() -> None:
    """Start the assistant and preload its configured local model."""
    print("Loading the local model...")
    settings = load_settings()
    model = OllamaModel(settings.ollama)
    model.warm_up()
    print(startup_message())
    ChatSession(model, settings.chat).run()


if __name__ == "__main__":
    main()
