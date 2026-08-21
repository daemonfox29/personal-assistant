"""Command-line entry point for the Personal Assistant."""

from personal_assistant.ollama_adapter import OllamaModel


def startup_message() -> str:
    """Return the assistant's initial status message."""
    return "Personal Assistant is ready."


def main() -> None:
    """Start the assistant and preload its configured local model."""
    print("Loading the local model...")
    OllamaModel().warm_up()
    print(startup_message())


if __name__ == "__main__":
    main()
