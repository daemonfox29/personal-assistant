"""Tests for app-owned on-demand SearXNG lifecycle management."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.error import URLError

from personal_assistant.search_runtime import (
    COLIMA_PROFILE_NAME,
    DOCKER_CONTEXT_NAME,
    SEARXNG_CONTAINER_NAME,
    SEARXNG_IMAGE,
    ColimaSearchRuntime,
    SearchRuntimeError,
)


class HealthResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return b"OK"


class FakeTimer:
    def __init__(self, delay: float, callback) -> None:
        self.delay = delay
        self.callback = callback
        self.started = False
        self.cancelled = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True


class SearchRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.settings_path = Path(self.temporary.name) / "settings.yml"
        self.settings_path.write_text("search: {}\n", encoding="utf-8")
        self.colima = str(Path(self.temporary.name) / "colima")
        self.docker = str(Path(self.temporary.name) / "docker")
        Path(self.colima).write_text("", encoding="utf-8")
        Path(self.docker).write_text("", encoding="utf-8")
        Path(self.colima).chmod(0o700)
        Path(self.docker).chmod(0o700)
        self.commands: list[tuple[tuple[str, ...], dict[str, str]]] = []
        self.timers: list[FakeTimer] = []
        self.profile_running = False

    def runner(self, arguments, _timeout, environment) -> int:
        self.commands.append((arguments, dict(environment or {})))
        if arguments[1:3] == ("status", COLIMA_PROFILE_NAME):
            return 0 if self.profile_running else 1
        if arguments[1:3] == ("start", COLIMA_PROFILE_NAME):
            self.profile_running = True
        if arguments[1:3] == ("stop", COLIMA_PROFILE_NAME):
            self.profile_running = False
        return 0

    def timer_factory(self, delay, callback) -> FakeTimer:
        timer = FakeTimer(delay, callback)
        self.timers.append(timer)
        return timer

    def runtime(self) -> ColimaSearchRuntime:
        return ColimaSearchRuntime(
            settings_path=self.settings_path,
            idle_seconds=120,
            runner=self.runner,
            timer_factory=self.timer_factory,
            health_opener=lambda _request, _timeout: HealthResponse(),
            colima_path=self.colima,
            docker_path=self.docker,
        )

    def test_first_search_starts_fixed_service_then_idle_stops_vm(self) -> None:
        runtime = self.runtime()

        self.assertEqual(runtime.run_while_active(lambda: "result"), "result")

        arguments = [item[0] for item in self.commands]
        start = next(item for item in arguments if item[1] == "start")
        self.assertEqual(start[2], COLIMA_PROFILE_NAME)
        self.assertIn("--memory=1", start)
        self.assertIn("--activate=false", start)
        self.assertIn("--runtime=docker", start)
        self.assertIn(f"--mount={self.settings_path.resolve().parent}:ro", start)
        run_arguments, run_environment = next(
            item for item in self.commands if "run" in item[0]
        )
        self.assertEqual(run_arguments[1:3], ("--context", DOCKER_CONTEXT_NAME))
        self.assertIn("127.0.0.1:8888:8080", run_arguments)
        self.assertIn("--pull=never", run_arguments)
        self.assertIn(SEARXNG_IMAGE, run_arguments)
        self.assertNotIn(run_environment["SEARXNG_SECRET"], run_arguments)
        self.assertEqual(len(run_environment["SEARXNG_SECRET"]), 43)
        self.assertEqual(self.timers[0].delay, 120)
        self.assertTrue(self.timers[0].started)

        self.timers[0].callback()

        self.assertIn(
            (
                self.docker,
                "--context",
                DOCKER_CONTEXT_NAME,
                "rm",
                "--force",
                SEARXNG_CONTAINER_NAME,
            ),
            [item[0] for item in self.commands],
        )
        self.assertEqual(
            self.commands[-1][0],
            (self.colima, "stop", COLIMA_PROFILE_NAME),
        )

    def test_later_search_resets_timer_without_restarting_service(self) -> None:
        runtime = self.runtime()

        runtime.run_while_active(lambda: None)
        runtime.run_while_active(lambda: None)

        starts = [
            command
            for command, _environment in self.commands
            if command[1:3] == ("start", COLIMA_PROFILE_NAME)
        ]
        self.assertEqual(len(starts), 1)
        self.assertTrue(self.timers[0].cancelled)
        self.assertTrue(self.timers[1].started)

    def test_externally_stopped_service_is_restarted_before_next_search(self) -> None:
        def health_opener(_request, _timeout):
            if not self.profile_running:
                raise URLError("synthetic stopped service")
            return HealthResponse()

        runtime = ColimaSearchRuntime(
            settings_path=self.settings_path,
            idle_seconds=120,
            runner=self.runner,
            timer_factory=self.timer_factory,
            health_opener=health_opener,
            colima_path=self.colima,
            docker_path=self.docker,
        )
        runtime.run_while_active(lambda: None)
        self.profile_running = False

        runtime.run_while_active(lambda: None)

        starts = [
            command
            for command, _environment in self.commands
            if command[1:3] == ("start", COLIMA_PROFILE_NAME)
        ]
        self.assertEqual(len(starts), 2)

    def test_cancelled_timer_callback_cannot_stop_a_newer_idle_session(self) -> None:
        runtime = self.runtime()

        runtime.run_while_active(lambda: None)
        stale_callback = self.timers[0].callback
        runtime.run_while_active(lambda: None)
        stale_callback()

        stops = [
            command
            for command, _environment in self.commands
            if command[1:3] == ("stop", COLIMA_PROFILE_NAME)
        ]
        self.assertEqual(stops, [])

        self.timers[1].callback()

        stops = [
            command
            for command, _environment in self.commands
            if command[1:3] == ("stop", COLIMA_PROFILE_NAME)
        ]
        self.assertEqual(len(stops), 1)

    def test_close_cancels_timer_and_stops_once(self) -> None:
        runtime = self.runtime()
        runtime.run_while_active(lambda: None)

        runtime.close()
        runtime.close()

        self.assertTrue(self.timers[0].cancelled)
        stops = [
            command
            for command, _environment in self.commands
            if command[1:3] == ("stop", COLIMA_PROFILE_NAME)
        ]
        self.assertEqual(len(stops), 1)
        with self.assertRaises(SearchRuntimeError):
            runtime.run_while_active(lambda: None)

    def test_unavailable_machine_fails_before_container_start(self) -> None:
        def failing_runner(arguments, _timeout, _environment) -> int:
            self.commands.append((arguments, {}))
            return 1

        runtime = ColimaSearchRuntime(
            settings_path=self.settings_path,
            runner=failing_runner,
            timer_factory=self.timer_factory,
            health_opener=lambda _request, _timeout: HealthResponse(),
            colima_path=self.colima,
            docker_path=self.docker,
        )

        with self.assertRaises(SearchRuntimeError):
            runtime.run_while_active(lambda: None)

        self.assertFalse(any("run" in command for command, _env in self.commands))

    def test_settings_must_be_a_regular_non_symlink_file(self) -> None:
        link = Path(self.temporary.name) / "linked.yml"
        link.symlink_to(self.settings_path)

        with self.assertRaises(ValueError):
            ColimaSearchRuntime(
                settings_path=link,
                colima_path=self.colima,
                docker_path=self.docker,
            )


if __name__ == "__main__":
    unittest.main()
