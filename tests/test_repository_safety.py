"""Checks for repository safety controls that protect future changes."""

from pathlib import Path
import re
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class RepositorySafetyTests(unittest.TestCase):
    def test_encrypted_database_dependency_is_exactly_pinned(self) -> None:
        project_metadata = (REPOSITORY_ROOT / "pyproject.toml").read_text()

        self.assertIn('"sqlcipher3==0.6.2"', project_metadata)

    def test_common_secret_files_are_ignored(self) -> None:
        ignore_rules = (REPOSITORY_ROOT / ".gitignore").read_text()

        for rule in (
            ".env.*",
            "*.key",
            "*.p12",
            "*.token",
            ".netrc",
            "credentials.json",
            "service-account*.json",
            "cookies*.json",
            "secrets/",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, ignore_rules.splitlines())

    def test_reusable_actions_are_immutable_sha_pinned(self) -> None:
        workflow = (
            REPOSITORY_ROOT / ".github" / "workflows" / "tests.yml"
        ).read_text()
        action_references = re.findall(r"uses:\s*[^@\s]+@([^\s]+)", workflow)

        self.assertTrue(action_references)
        for reference in action_references:
            with self.subTest(reference=reference):
                self.assertRegex(reference, r"^[0-9a-f]{40}$")

    def test_checkout_does_not_persist_credentials(self) -> None:
        workflow = (
            REPOSITORY_ROOT / ".github" / "workflows" / "tests.yml"
        ).read_text()

        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)


if __name__ == "__main__":
    unittest.main()
