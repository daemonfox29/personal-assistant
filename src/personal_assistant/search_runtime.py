"""App-owned lifecycle for the optional local SearXNG Colima service."""

from collections.abc import Callable, Mapping
from pathlib import Path
import os
import secrets
import subprocess
from threading import Lock, Timer
import time
from typing import BinaryIO, Protocol, TypeVar
from urllib.error import HTTPError, URLError
from urllib.request import Request

from personal_assistant.local_http import open_local


COLIMA_PROFILE_NAME = "personal-assistant-search"
DOCKER_CONTEXT_NAME = f"colima-{COLIMA_PROFILE_NAME}"
SEARXNG_CONTAINER_NAME = "personal-assistant-searxng"
SEARXNG_IMAGE = (
    "ghcr.io/searxng/searxng:2026.8.20-8d3dd0cd4@"
    "sha256:3cb8eba87bb347613fab9dfe87d448c21300b8f0648295c93b85f4246e93ae73"
)
DEFAULT_SEARCH_IDLE_SECONDS = 120.0
MAX_SEARCH_STARTUP_SECONDS = 45.0
COLIMA_PATH = "/opt/homebrew/bin/colima"
DOCKER_PATH = "/opt/homebrew/bin/docker"


class SearchRuntimeError(RuntimeError):
    """The reviewed local search service could not be managed safely."""


class TimerHandle(Protocol):
    def cancel(self) -> None:
        """Cancel the pending callback."""

    def start(self) -> None:
        """Start the pending callback."""


CommandRunner = Callable[[tuple[str, ...], float, Mapping[str, str] | None], int]
TimerFactory = Callable[[float, Callable[[], None]], TimerHandle]
HealthOpener = Callable[[Request, float], BinaryIO]
ResultT = TypeVar("ResultT")


def default_searxng_settings_path() -> Path:
    """Return the checked-in fixed SearXNG configuration path."""

    return Path(__file__).resolve().parents[2] / "deploy" / "searxng" / "settings.yml"


def _run_command(
    arguments: tuple[str, ...],
    timeout_seconds: float,
    extra_environment: Mapping[str, str] | None,
) -> int:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key
        in {
            "DOCKER_CONFIG",
            "HOME",
            "PATH",
            "TMPDIR",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "XDG_RUNTIME_DIR",
        }
    }
    if extra_environment is not None:
        environment.update(extra_environment)
    try:
        completed = subprocess.run(
            arguments,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_seconds,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SearchRuntimeError("The local search runtime command failed.") from error
    return completed.returncode


def _timer_factory(delay: float, callback: Callable[[], None]) -> Timer:
    timer = Timer(delay, callback)
    timer.daemon = True
    return timer


class ColimaSearchRuntime:
    """Start SearXNG on demand and stop its dedicated VM after idle time."""

    def __init__(
        self,
        *,
        settings_path: Path | None = None,
        idle_seconds: float = DEFAULT_SEARCH_IDLE_SECONDS,
        runner: CommandRunner = _run_command,
        timer_factory: TimerFactory = _timer_factory,
        health_opener: HealthOpener = open_local,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        colima_path: str = COLIMA_PATH,
        docker_path: str = DOCKER_PATH,
    ) -> None:
        selected_path = (
            default_searxng_settings_path()
            if settings_path is None
            else settings_path
        )
        if not isinstance(selected_path, Path):
            raise TypeError("Search runtime settings require a path.")
        if selected_path.is_symlink() or not selected_path.is_file():
            raise ValueError("The reviewed search runtime settings are unavailable.")
        if (
            isinstance(idle_seconds, bool)
            or not isinstance(idle_seconds, (int, float))
            or not 1.0 <= float(idle_seconds) <= 3600.0
        ):
            raise ValueError("Search runtime idle time is outside its safe range.")
        if not all(
            callable(value)
            for value in (runner, timer_factory, health_opener, monotonic, sleeper)
        ):
            raise TypeError("Search runtime dependencies must be callable.")
        if not all(
            isinstance(value, str) and Path(value).is_absolute()
            for value in (colima_path, docker_path)
        ):
            raise ValueError("Search runtime executable paths must be absolute.")
        self._settings_path = selected_path.resolve(strict=True)
        self._idle_seconds = float(idle_seconds)
        self._runner = runner
        self._timer_factory = timer_factory
        self._health_opener = health_opener
        self._monotonic = monotonic
        self._sleeper = sleeper
        self._colima = colima_path
        self._docker = docker_path
        self._lock = Lock()
        self._timer: TimerHandle | None = None
        self._timer_generation = 0
        self._running = False
        self._active = 0
        self._closed = False

    @property
    def idle_seconds(self) -> float:
        return self._idle_seconds

    def run_while_active(self, operation: Callable[[], ResultT]) -> ResultT:
        """Run one search while preventing the idle callback from stopping it."""

        if not callable(operation):
            raise TypeError("Search runtime operation must be callable.")
        with self._lock:
            if self._closed:
                raise SearchRuntimeError("The local search runtime is closed.")
            self._cancel_timer_locked()
            if not self._running:
                self._start_locked()
            self._active += 1
        try:
            return operation()
        finally:
            with self._lock:
                self._active -= 1
                if self._active == 0:
                    if self._closed:
                        self._stop_locked()
                    else:
                        self._schedule_stop_locked()

    def close(self) -> None:
        """Cancel future work and release the dedicated container and VM."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._cancel_timer_locked()
            if self._active == 0:
                self._stop_locked()

    def _start_locked(self) -> None:
        if not all(
            Path(value).is_file() and os.access(value, os.X_OK)
            for value in (self._colima, self._docker)
        ):
            raise SearchRuntimeError(
                "The open-source Colima search runtime is not installed."
            )
        if self._runner(
            (self._colima, "status", COLIMA_PROFILE_NAME),
            10.0,
            None,
        ) != 0:
            status = self._runner(
                (
                    self._colima,
                    "start",
                    COLIMA_PROFILE_NAME,
                    "--activate=false",
                    "--arch=aarch64",
                    "--binfmt=false",
                    "--cpus=2",
                    "--disk=10",
                    "--memory=1",
                    f"--mount={self._settings_path.parent}:ro",
                    "--mount-type=virtiofs",
                    "--runtime=docker",
                    "--ssh-agent=false",
                    "--ssh-config=false",
                    "--vm-type=vz",
                ),
                90.0,
                None,
            )
            if status != 0:
                raise SearchRuntimeError(
                    "The dedicated search machine could not start."
                )
        if self._runner(
            (self._docker, "--context", DOCKER_CONTEXT_NAME, "info"),
            15.0,
            None,
        ) != 0:
            self._stop_commands()
            raise SearchRuntimeError("The dedicated search machine is unavailable.")
        self._runner(
            (
                self._docker,
                "--context",
                DOCKER_CONTEXT_NAME,
                "rm",
                "--force",
                SEARXNG_CONTAINER_NAME,
            ),
            15.0,
            None,
        )
        session_secret = secrets.token_urlsafe(32)
        try:
            status = self._runner(
                (
                    self._docker,
                    "--context",
                    DOCKER_CONTEXT_NAME,
                    "run",
                    "--detach",
                    "--pull=never",
                    "--name",
                    SEARXNG_CONTAINER_NAME,
                    "--publish",
                    "127.0.0.1:8888:8080",
                    "--read-only",
                    "--tmpfs",
                    "/tmp:rw,size=32m,mode=1777",
                    "--tmpfs",
                    "/var/cache/searxng:rw,size=32m,mode=0750",
                    "--security-opt",
                    "no-new-privileges",
                    "--cap-drop",
                    "all",
                    "--memory",
                    "384m",
                    "--pids-limit",
                    "256",
                    "--env",
                    "SEARXNG_SECRET",
                    "--volume",
                    f"{self._settings_path}:/etc/searxng/settings.yml:ro",
                    SEARXNG_IMAGE,
                ),
                30.0,
                {"SEARXNG_SECRET": session_secret},
            )
        finally:
            session_secret = ""
        if status != 0 or not self._wait_for_health():
            self._stop_commands()
            raise SearchRuntimeError("The local search service could not start.")
        self._running = True

    def _wait_for_health(self) -> bool:
        deadline = self._monotonic() + MAX_SEARCH_STARTUP_SECONDS
        request = Request(
            "http://127.0.0.1:8888/healthz",
            headers={"Accept": "text/plain"},
            method="GET",
        )
        while self._monotonic() < deadline:
            try:
                with self._health_opener(request, 1.0) as response:
                    if getattr(response, "status", None) == 200:
                        return response.read(16).strip() == b"OK"
            except (HTTPError, URLError, OSError, TimeoutError):
                pass
            self._sleeper(0.25)
        return False

    def _schedule_stop_locked(self) -> None:
        self._cancel_timer_locked()
        generation = self._timer_generation
        timer = self._timer_factory(
            self._idle_seconds,
            lambda: self._idle_stop(generation),
        )
        self._timer = timer
        timer.start()

    def _cancel_timer_locked(self) -> None:
        self._timer_generation += 1
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _idle_stop(self, generation: int) -> None:
        with self._lock:
            if generation != self._timer_generation:
                return
            self._timer = None
            if not self._closed and self._active == 0:
                self._stop_locked()

    def _stop_locked(self) -> None:
        if not self._running:
            return
        self._stop_commands()
        self._running = False

    def _stop_commands(self) -> None:
        self._runner(
            (
                self._docker,
                "--context",
                DOCKER_CONTEXT_NAME,
                "rm",
                "--force",
                SEARXNG_CONTAINER_NAME,
            ),
            15.0,
            None,
        )
        self._runner(
            (self._colima, "stop", COLIMA_PROFILE_NAME),
            45.0,
            None,
        )
