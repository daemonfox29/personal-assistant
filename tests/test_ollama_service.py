"""Checks for the local Ollama service manager."""

import unittest
from unittest.mock import Mock

from personal_assistant.ollama_service import (
    OllamaService,
    OllamaServiceSettings,
    OllamaUnavailableError,
)


class OllamaServiceTests(unittest.TestCase):
    """Verify that the service starts only when it is needed."""

    def test_running_service_is_not_started_again(self) -> None:
        launch_service = Mock()
        service = OllamaService(
            health_check=Mock(return_value=True),
            launch_service=launch_service,
            sleep=Mock(),
        )

        service.ensure_available()

        launch_service.assert_not_called()

    def test_missing_service_is_started_and_waited_for(self) -> None:
        health_check = Mock(side_effect=[False, False, True])
        launch_service = Mock()
        sleep = Mock()
        service = OllamaService(
            settings=OllamaServiceSettings(startup_attempts=2),
            health_check=health_check,
            launch_service=launch_service,
            sleep=sleep,
        )

        service.ensure_available()

        launch_service.assert_called_once_with()
        self.assertEqual(sleep.call_count, 2)

    def test_unavailable_service_raises_an_error(self) -> None:
        service = OllamaService(
            settings=OllamaServiceSettings(startup_attempts=1),
            health_check=Mock(return_value=False),
            launch_service=Mock(),
            sleep=Mock(),
        )

        with self.assertRaises(OllamaUnavailableError):
            service.ensure_available()
