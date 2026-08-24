"""Behavioral checks for every advertised production Compose entry point."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = (
    REPO_ROOT / "docker-compose.yml",
    REPO_ROOT / "deploy" / "docker-compose.yml",
)
TEST_JWT = "compose-contract-only-0123456789abcdef"


def compose_config(compose_file: Path, jwt_secret: str = TEST_JWT) -> dict:
    """Render one production Compose entry point into its normalized model.

    Args:
        compose_file: Compose file users may launch.
        jwt_secret: Signing secret written to the controlled environment file.

    Returns:
        The normalized Compose model decoded from JSON.

    Raises:
        AssertionError: If Compose cannot render the supplied file.
    """
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".env",
        delete=False,
    ) as env_file:
        env_file.write(f"JWT_SECRET_KEY={jwt_secret}\n")
        env_path = Path(env_file.name)

    environment = os.environ.copy()
    for name in ("JWT_SECRET_KEY", "DEBUG", "CORS_ORIGINS", "BACKEND_INTERNAL_URL"):
        environment.pop(name, None)

    try:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                str(env_path),
                "--profile",
                "with-ollama",
                "--profile",
                "with-cache",
                "-f",
                str(compose_file),
                "config",
                "--format",
                "json",
            ],
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        env_path.unlink(missing_ok=True)

    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def missing_secret_result(compose_file: Path) -> subprocess.CompletedProcess[str]:
    """Try rendering a Compose entry point with a deliberately blank secret.

    Args:
        compose_file: Compose file users may launch.

    Returns:
        The completed Compose process, including its diagnostic output.
    """
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".env",
        delete=False,
    ) as env_file:
        env_file.write("JWT_SECRET_KEY=\n")
        env_path = Path(env_file.name)

    environment = os.environ.copy()
    environment.pop("JWT_SECRET_KEY", None)
    try:
        return subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                str(env_path),
                "-f",
                str(compose_file),
                "config",
            ],
            cwd=REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        env_path.unlink(missing_ok=True)


class ComposeContractTests(unittest.TestCase):
    """Exercise normalized production configuration rather than source text."""

    def test_every_entry_point_rejects_a_blank_jwt(self) -> None:
        """No advertised Compose path may render without a signing key."""
        for compose_file in COMPOSE_FILES:
            with self.subTest(compose_file=compose_file):
                result = missing_secret_result(compose_file)
                output = result.stdout + result.stderr
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("JWT_SECRET_KEY is required", output)

    def test_every_entry_point_has_the_canonical_production_contract(self) -> None:
        """Legacy invocation must render the same hardened backend and frontend."""
        root = compose_config(COMPOSE_FILES[0])

        for compose_file in COMPOSE_FILES:
            with self.subTest(compose_file=compose_file):
                rendered = compose_config(compose_file)
                backend = rendered["services"]["backend"]
                frontend = rendered["services"]["frontend"]

                self.assertEqual(backend["build"], root["services"]["backend"]["build"])
                self.assertEqual(frontend["build"], root["services"]["frontend"]["build"])
                self.assertEqual(backend["environment"]["APP_ENV"], "production")
                self.assertEqual(backend["environment"]["DEBUG"], "false")
                self.assertEqual(
                    backend["environment"]["CORS_ORIGINS"],
                    "http://localhost:3000",
                )
                self.assertIn("/readyz", " ".join(backend["healthcheck"]["test"]))
                self.assertEqual(
                    frontend["environment"]["BACKEND_INTERNAL_URL"],
                    "http://backend:8000",
                )

    def test_persistent_service_state_uses_engine_managed_volumes(self) -> None:
        """Fresh rootful launches must not create root-owned host bind folders."""
        expected_targets = {
            "backend": {"/app/data", "/app/models", "/app/uploads"},
            "ollama": {"/root/.ollama"},
            "redis": {"/data"},
        }

        for compose_file in COMPOSE_FILES:
            rendered = compose_config(compose_file)
            for service_name, targets in expected_targets.items():
                with self.subTest(compose_file=compose_file, service=service_name):
                    mounts = {
                        mount["target"]: mount
                        for mount in rendered["services"][service_name]["volumes"]
                    }
                    self.assertTrue(targets.issubset(mounts))
                    for target in targets:
                        self.assertEqual(mounts[target]["type"], "volume")


if __name__ == "__main__":
    unittest.main()
