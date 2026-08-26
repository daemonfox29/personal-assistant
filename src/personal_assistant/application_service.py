"""Narrow lifecycle boundary exposed to trusted local user interfaces."""

from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from threading import Lock
from uuid import uuid4

from personal_assistant.audit_file import AuditFileSettings, JsonLinesAuditSink
from personal_assistant.backup import BackupError
from personal_assistant.config import AppSettings
from personal_assistant.conversation import ConversationEvent, ConversationService
from personal_assistant.memory_analyzer import (
    ModelMemorySuggestionAnalyzer,
    PostResponseMemoryWorker,
)
from personal_assistant.memory_runtime import MemoryRuntime
from personal_assistant.ollama_adapter import OllamaModel
from personal_assistant.model import (
    MalformedModelResponseError,
    ModelError,
    ModelNotFoundError,
    ModelUnavailableError,
)
from personal_assistant.portable_security import (
    PortableSecurityManager,
    PortableSecuritySettings,
    SecuritySetupError,
)


class ApplicationServiceError(RuntimeError):
    """A fixed safe failure suitable for display by a trusted UI."""


class ApplicationSetupError(ApplicationServiceError):
    pass


class ApplicationOpenError(ApplicationServiceError):
    pass


class ApplicationLaunchState(StrEnum):
    SETUP_REQUIRED = "setup_required"
    UNLOCK_REQUIRED = "unlock_required"
    SESSION_ONLY = "session_only"


@dataclass(frozen=True)
class ApplicationSessionInfo:
    model_name: str
    persistent_memory: bool
    startup_notices: tuple[str, ...] = ()


class AssistantApplicationService:
    """Own one assistant session without exposing its authority-bearing parts."""

    def __init__(
        self,
        conversation: ConversationService,
        runtime: MemoryRuntime | None,
        info: ApplicationSessionInfo,
    ) -> None:
        self._conversation = conversation
        self._runtime = runtime
        self._info = info
        self._lock = Lock()
        self._closed = False

    @property
    def info(self) -> ApplicationSessionInfo:
        return self._info

    def events_for(
        self,
        user_text: str,
        *,
        max_response_tokens: int | None = None,
    ) -> tuple[ConversationEvent, ...]:
        """Return one bounded event stream as immutable UI-facing values."""

        with self._lock:
            if self._closed:
                raise ApplicationOpenError("This assistant session is closed.")
        return tuple(
            self._conversation.events_for(
                user_text,
                max_response_tokens=max_response_tokens,
            )
        )

    def iter_events(
        self,
        user_text: str,
        *,
        max_response_tokens: int | None = None,
    ) -> Iterator[ConversationEvent]:
        """Yield UI-facing events incrementally for streaming presentation."""

        with self._lock:
            if self._closed:
                raise ApplicationOpenError("This assistant session is closed.")
        yield from self._conversation.events_for(
            user_text,
            max_response_tokens=max_response_tokens,
        )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._conversation.close()
        if self._runtime is not None:
            self._runtime.close()


class AssistantApplicationFactory:
    """Perform setup and compose sessions behind fixed safe UI outcomes."""

    def __init__(self, settings: AppSettings) -> None:
        if not isinstance(settings, AppSettings):
            raise TypeError("Application factory requires validated settings.")
        self._settings = settings

    def launch_state(self) -> ApplicationLaunchState:
        if not self._settings.memory.enabled:
            return ApplicationLaunchState.SESSION_ONLY
        security = self._security()
        manifest = self._manifest_path
        try:
            configured = security.is_configured
        except Exception as error:
            raise ApplicationOpenError(
                "Persistent-memory security configuration is unavailable."
            ) from error
        if configured:
            database = self._database_path
            if (
                not database.exists()
                or database.is_symlink()
                or not database.is_file()
            ):
                raise ApplicationOpenError(
                    "The encrypted memory database is missing or unsafe. Startup "
                    "was blocked to prevent creating a blank replacement."
                )
            return ApplicationLaunchState.UNLOCK_REQUIRED
        if manifest.exists() or manifest.is_symlink():
            raise ApplicationOpenError(
                "Persistent-memory security configuration is unavailable."
            )
        return ApplicationLaunchState.SETUP_REQUIRED

    def setup(
        self,
        recovery_passphrase: str,
        recovery_confirmation: str,
        high_risk_passcode: str,
        passcode_confirmation: str,
    ) -> None:
        if self.launch_state() is not ApplicationLaunchState.SETUP_REQUIRED:
            raise ApplicationSetupError("Persistent memory is already configured.")
        manifest = self._manifest_path
        database = self._database_path
        database_preexisted = database.exists() or database.is_symlink()
        sidecars = tuple(
            Path(f"{database}{suffix}") for suffix in ("-journal", "-wal", "-shm")
        )
        sidecars_preexisted = {
            path: path.exists() or path.is_symlink() for path in sidecars
        }
        completed = False
        try:
            self._security().setup(
                recovery_passphrase,
                recovery_confirmation,
                high_risk_passcode,
                passcode_confirmation,
                uuid4(),
            )
            runtime = MemoryRuntime.open(
                self._settings.memory,
                recovery_passphrase,
                audit_sink=self._audit_sink(),
                create_database=True,
            )
            runtime.close()
            completed = True
        except SecuritySetupError as error:
            raise ApplicationSetupError(self._safe_setup_message(error)) from error
        except Exception as error:
            raise ApplicationSetupError(
                "Persistent-memory setup failed safely; no setup was completed."
            ) from error
        finally:
            recovery_passphrase = recovery_confirmation = ""
            high_risk_passcode = passcode_confirmation = ""
            if not completed:
                self._unlink_new_file(manifest)
                if not database_preexisted:
                    self._unlink_new_file(database)
                for path in sidecars:
                    if not sidecars_preexisted[path]:
                        self._unlink_new_file(path)

    def open(
        self,
        recovery_passphrase: str | None = None,
        *,
        session_only: bool = False,
    ) -> AssistantApplicationService:
        runtime: MemoryRuntime | None = None
        notices: list[str] = []
        try:
            if not session_only and self._settings.memory.enabled:
                if self.launch_state() is not ApplicationLaunchState.UNLOCK_REQUIRED:
                    raise ApplicationOpenError("Persistent memory is not configured.")
                if recovery_passphrase is None:
                    raise ApplicationOpenError("A recovery passphrase is required.")
                runtime = MemoryRuntime.open(
                    self._settings.memory,
                    recovery_passphrase,
                    audit_sink=self._audit_sink(),
                )
                if runtime.backup_manager is not None:
                    try:
                        runtime.create_daily_backup(uuid4())
                    except BackupError:
                        notices.append(
                            "Daily encrypted backup was safely skipped; check its "
                            "destination in settings."
                        )
            model = OllamaModel(self._settings.ollama)
            model.warm_up()
            worker = None
            if runtime is not None and self._settings.memory.automatic_suggestions:
                analyzer = ModelMemorySuggestionAnalyzer(
                    model,
                    self._settings.ollama.model_name,
                    audit_sink=runtime.audit_sink,
                )
                worker = PostResponseMemoryWorker(
                    analyzer,
                    runtime.capture,
                    audit_sink=runtime.audit_sink,
                )
            conversation = ConversationService(
                model,
                self._settings.chat,
                context_window_tokens=self._settings.ollama.context_tokens,
                default_response_tokens=self._settings.ollama.max_response_tokens,
                memory_context_provider=(
                    None if runtime is None else runtime.context_provider
                ),
                explicit_memory_handler=runtime,
                post_response_worker=worker,
            )
            return AssistantApplicationService(
                conversation,
                runtime,
                ApplicationSessionInfo(
                    self._settings.ollama.model_name,
                    runtime is not None,
                    tuple(notices),
                ),
            )
        except ApplicationServiceError:
            if runtime is not None:
                runtime.close()
            raise
        except Exception as error:
            if runtime is not None:
                runtime.close()
            raise ApplicationOpenError(self._safe_open_message(error)) from error
        finally:
            recovery_passphrase = None

    @property
    def _manifest_path(self) -> Path:
        return self._settings.memory.data_directory / "security.json"

    @property
    def _database_path(self) -> Path:
        return self._settings.memory.data_directory / "memory.db"

    def _audit_sink(self) -> JsonLinesAuditSink:
        return JsonLinesAuditSink(
            AuditFileSettings(self._settings.memory.data_directory / "audit.jsonl")
        )

    def _security(self) -> PortableSecurityManager:
        return PortableSecurityManager(
            PortableSecuritySettings(self._manifest_path),
            audit_sink=self._audit_sink(),
        )

    @staticmethod
    def _safe_open_message(error: Exception) -> str:
        if isinstance(error, ModelUnavailableError):
            return "Ollama is unavailable. Check that it is installed and try again."
        if isinstance(error, ModelNotFoundError):
            return "The configured local model is not installed."
        if isinstance(error, MalformedModelResponseError):
            return "Ollama returned an unreadable response. Please try again."
        if isinstance(error, ModelError):
            return "The local model request failed. Please try again."
        return "The assistant could not start safely. Check local configuration."

    @staticmethod
    def _safe_setup_message(error: SecuritySetupError) -> str:
        messages = {
            "Recovery passphrase confirmation does not match.": (
                "The recovery passphrase entries do not match. Re-enter both."
            ),
            "Recovery passphrase length is invalid.": (
                "The recovery passphrase must contain at least 12 characters."
            ),
            "High-risk passcode confirmation does not match.": (
                "The high-risk passcode entries do not match. Re-enter both."
            ),
            "High-risk passcode length is invalid.": (
                "The high-risk passcode must contain at least 8 characters."
            ),
            "Recovery passphrase and high-risk passcode must be different.": (
                "The recovery passphrase and high-risk passcode must be different."
            ),
        }
        return messages.get(
            str(error),
            "Persistent-memory setup failed safely; no setup was completed.",
        )

    @staticmethod
    def _unlink_new_file(path: Path) -> None:
        try:
            if path.is_file() and not path.is_symlink():
                path.unlink()
        except OSError:
            pass
