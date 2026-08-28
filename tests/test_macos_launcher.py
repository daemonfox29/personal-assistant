"""Regression checks for the macOS development launcher process boundary."""

from pathlib import Path
import unittest


class MacOSLauncherTests(unittest.TestCase):
    def test_launcher_executes_the_ui_entry_point_without_uv_parent(self) -> None:
        source = (
            Path(__file__).parents[1] / "launchers" / "macos" / "launcher.c"
        ).read_text(encoding="utf-8")

        self.assertIn(".venv/bin/personal-assistant-ui", source)
        self.assertIn("execl(entry_point, entry_point", source)
        self.assertIn(
            '"PERSONAL_ASSISTANT_TEST_ONLY_SKIP_MACOS_USER_PRESENCE"',
            source,
        )
        self.assertIn("<Security/Security.h>", source)
        self.assertIn("SecKeychainFindGenericPassword", source)
        self.assertIn('"PERSONAL_ASSISTANT_TEST_ONLY_RECOVERY_FD"', source)
        self.assertIn("clear_memory(contents, length)", source)
        self.assertNotIn('"/usr/bin/security"', source)
        self.assertNotIn('"run", "--locked"', source)

    def test_installer_synchronizes_the_locked_environment(self) -> None:
        source = (
            Path(__file__).parents[1] / "launchers" / "install-macos-launcher.sh"
        ).read_text(encoding="utf-8")

        self.assertIn(
            '"$uv_path" --directory "$project_dir" sync --locked', source
        )
        self.assertIn("-framework Security", source)
        self.assertIn("/usr/bin/awk '{ print; print }'", source)
        self.assertIn('-T "" -T "$launcher" -w', source)
        self.assertIn("--verify-testing-credential", source)


if __name__ == "__main__":
    unittest.main()
