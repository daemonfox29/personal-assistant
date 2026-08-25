"""Command-line entry point for the Personal Assistant."""

from getpass import getpass
from uuid import uuid4

from personal_assistant.audit import AuditError
from personal_assistant.audit_file import AuditFileSettings, JsonLinesAuditSink
from personal_assistant.backup import BackupError
from personal_assistant.chat import ChatSession
from personal_assistant.config import MemorySettings, load_settings
from personal_assistant.encrypted_database import EncryptedDatabaseError
from personal_assistant.memory_runtime import MemoryRuntime
from personal_assistant.memory_analyzer import (
    ModelMemorySuggestionAnalyzer,
    PostResponseMemoryWorker,
)
from personal_assistant.migration import MigrationError
from personal_assistant.ollama_adapter import OllamaModel
from personal_assistant.model import (
    MalformedModelResponseError,
    ModelError,
    ModelNotFoundError,
    ModelUnavailableError,
)
from personal_assistant.portable_security import (
    PortableSecurityError,
    PortableSecurityManager,
    PortableSecuritySettings,
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
        memory_runtime = _open_memory_runtime(settings.memory)
        memory_worker = None
        if memory_runtime is not None and settings.memory.automatic_suggestions:
            analyzer = ModelMemorySuggestionAnalyzer(
                model,
                settings.ollama.model_name,
                audit_sink=memory_runtime.audit_sink,
            )
            memory_worker = PostResponseMemoryWorker(
                analyzer,
                memory_runtime.capture,
                audit_sink=memory_runtime.audit_sink,
            )
        try:
            print(startup_message())
            ChatSession(
                model,
                settings.chat,
                context_window_tokens=settings.ollama.context_tokens,
                default_response_tokens=settings.ollama.max_response_tokens,
                memory_context_provider=(
                    None if memory_runtime is None else memory_runtime.context_provider
                ),
                explicit_memory_handler=memory_runtime,
                post_response_worker=memory_worker,
            ).run()
        finally:
            if memory_worker is not None:
                memory_worker.close()
            if memory_runtime is not None:
                memory_runtime.close()
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
    except (PortableSecurityError, EncryptedDatabaseError, MigrationError, AuditError):
        print(
            "Persistent memory could not be unlocked safely. "
            "The assistant did not start."
        )


def _open_memory_runtime(memory_settings: MemorySettings) -> MemoryRuntime | None:
    if not memory_settings.enabled:
        return None
    audit_sink = JsonLinesAuditSink(
        AuditFileSettings(memory_settings.data_directory / "audit.jsonl")
    )
    security = PortableSecurityManager(
        PortableSecuritySettings(memory_settings.data_directory / "security.json"),
        audit_sink=audit_sink,
    )
    manifest_path = memory_settings.data_directory / "security.json"
    if not security.is_configured:
        if manifest_path.exists() or manifest_path.is_symlink():
            raise PortableSecurityError("Portable security configuration is unsafe.")
        print(
            "Persistent memory is not set up; continuing in session-only mode. "
            "Run 'python -m personal_assistant.memory_admin setup' when ready."
        )
        return None
    recovery_passphrase = getpass("Recovery passphrase: ")
    try:
        runtime = MemoryRuntime.open(
            memory_settings,
            recovery_passphrase,
            audit_sink=audit_sink,
        )
    finally:
        recovery_passphrase = ""
    if runtime.backup_manager is not None:
        try:
            runtime.create_daily_backup(uuid4())
        except BackupError:
            print("Daily encrypted backup was safely skipped; check its destination.")
    print("Persistent memory is unlocked for this session.")
    return runtime


if __name__ == "__main__":
    main()
