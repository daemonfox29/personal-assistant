"""Command-line entry point for the Personal Assistant."""

from personal_assistant.chat import ChatSession
from personal_assistant.config import load_settings
from personal_assistant.ollama_adapter import OllamaModel
from personal_assistant.model import (
    MalformedModelResponseError,
    ModelError,
    ModelNotFoundError,
    ModelUnavailableError,
)


def startup_message() -> str:
    """Return the assistant's initial status message."""
    return "Personal Assistant is ready."


def main() -> None:
    """Start the assistant and preload its configured local model."""
    try:
        print("Loading the local model...")
        settings = load_settings()
        model = OllamaModel(settings.ollama)
        model.warm_up()
        print(startup_message())
        ChatSession(
            model,
            settings.chat,
            context_window_tokens=settings.ollama.context_tokens,
            default_response_tokens=settings.ollama.max_response_tokens,
        ).run()
    except KeyboardInterrupt:
        print("\nStartup cancelled.")
    except ModelUnavailableError:
        print("Ollama is unavailable. Check that it is installed and try again.")
    except ModelNotFoundError:
        print("The configured local model is not installed.")
    except MalformedModelResponseError:
        print("Ollama returned an unreadable response. Please try again.")
    except ModelError:
        print("The local model request failed. Please try again.")
    except ValueError:
        print("The assistant configuration is invalid. Check local settings.")


if __name__ == "__main__":
    main()
