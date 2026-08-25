"""Checks for repository safety controls that protect future changes."""

import ast
from pathlib import Path
import re
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class RepositorySafetyTests(unittest.TestCase):
    def test_memory_repository_sql_is_fixed_source_code(self) -> None:
        source = (
            REPOSITORY_ROOT
            / "src"
            / "personal_assistant"
            / "memory_repository.py"
        ).read_text()
        tree = ast.parse(source)
        execute_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
        ]

        self.assertTrue(execute_calls)
        for call in execute_calls:
            with self.subTest(line=call.lineno):
                self.assertTrue(call.args)
                self.assertIsInstance(call.args[0], ast.Constant)
                self.assertIsInstance(call.args[0].value, str)

    def test_encrypted_database_dependency_is_exactly_pinned(self) -> None:
        project_metadata = (REPOSITORY_ROOT / "pyproject.toml").read_text()

        self.assertIn('"sqlcipher3==0.6.2"', project_metadata)

    def test_native_ui_dependency_is_minimal_and_exactly_pinned(self) -> None:
        project_metadata = (REPOSITORY_ROOT / "pyproject.toml").read_text()
        lockfile = (REPOSITORY_ROOT / "uv.lock").read_text()

        self.assertIn('"pyside6-essentials==6.11.2"', project_metadata)
        self.assertNotIn('"pyside6==', project_metadata)
        self.assertIn('name = "pyside6-essentials"', lockfile)
        self.assertIn('version = "6.11.2"', lockfile)

    def test_uv_version_lockfile_and_ci_are_pinned(self) -> None:
        project_metadata = (REPOSITORY_ROOT / "pyproject.toml").read_text()
        lockfile = (REPOSITORY_ROOT / "uv.lock").read_text()
        workflow = (
            REPOSITORY_ROOT / ".github" / "workflows" / "tests.yml"
        ).read_text()

        self.assertIn('required-version = "==0.12.5"', project_metadata)
        self.assertIn('requires-python = ">=3.11,<3.15"', project_metadata)
        self.assertIn('name = "sqlcipher3"', lockfile)
        self.assertIn('version = "0.6.2"', lockfile)
        self.assertIn("uv sync --locked", workflow)
        self.assertIn("uv run --locked --no-sync", workflow)

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
