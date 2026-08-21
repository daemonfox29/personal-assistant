"""Command-line entry point for the Personal Assistant."""


def startup_message() -> str:
    """Return the assistant's initial status message."""
    return "Personal Assistant is ready."


def main() -> None:
    """Run the assistant."""
    print(startup_message())


if __name__ == "__main__":
    main()