"""Behavioral checks for every advertised production Compose entry point."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = (
    REPO_ROOT / "docker-compose.yml",
    REPO_ROOT / "deploy" / "docker-compose.yml",
)
TEST_JWT = "compose-contract-only-0123456789abcdef"
DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-base"
DEFAULT_EMBEDDING_DIMENSION = "768"
OBSERVED_COLD_START_SECONDS = 91
MINIMUM_START_PERIOD_SECONDS = 600
EXPECTED_WAIT_TIMEOUT_SECONDS = 900
EXPECTED_HEALTH_FAILURE_BOUNDARY_SECONDS = 730


def compose_config(
    compose_file: Path,
    jwt_secret: str = TEST_JWT,
    environment_overrides: dict[str, str] | None = None,
) -> dict:
    """Render one production Compose entry point into its normalized model.

    Args:
        compose_file: Compose file users may launch.
        jwt_secret: Signing secret written to the controlled environment file.
        environment_overrides: Controlled host values passed to Compose.

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
    for name in (
        "JWT_SECRET_KEY",
        "DEBUG",
        "CORS_ORIGINS",
        "BACKEND_INTERNAL_URL",
        "EMB_MODEL_NAME",
        "EMB_DIMENSION",
    ):
        environment.pop(name, None)
    environment.update(environment_overrides or {})

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


def duration_seconds(value: str) -> int:
    """Convert a normalized Compose duration to whole seconds.

    Args:
        value: Normalized duration containing integer `h`, `m`, or `s` parts.

    Returns:
        The represented number of seconds.

    Raises:
        AssertionError: If the normalized duration has an unexpected shape.
    """
    parts = re.findall(r"(\d+)([hms])", value)
    reconstructed = "".join(f"{amount}{unit}" for amount, unit in parts)
    assert parts and reconstructed == value, f"Unexpected Compose duration: {value}"
    multipliers = {"h": 3600, "m": 60, "s": 1}
    return sum(int(amount) * multipliers[unit] for amount, unit in parts)


def ci_runtime_wait_timeouts() -> list[int]:
    """Read the wait budgets declared by the two CI runtime smoke commands.

    Returns:
        Wait-timeout values from root and compatibility runtime smoke commands.
    """
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8",
    )
    return [
        int(value)
        for value in re.findall(
            r"docker compose[^\n]*\bup -d --wait --wait-timeout (\d+)",
            workflow,
        )
    ]


def ci_runtime_smoke_steps() -> list[tuple[str, dict[str, str], str]]:
    """Parse runtime smoke environments and scripts from the CI workflow.

    Returns:
        Step names paired with their environment mappings and shell scripts.
    """
    workflow_lines = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8",
    ).splitlines()
    steps: list[tuple[str, dict[str, str], str]] = []
    current_name: str | None = None
    current_environment: dict[str, str] = {}
    current_run_lines: list[str] = []
    section: str | None = None

    for line in [*workflow_lines, "      - name: end runtime smoke scan"]:
        if line.startswith("      - name: "):
            if current_name is not None:
                steps.append(
                    (
                        current_name,
                        current_environment,
                        "\n".join(current_run_lines),
                    )
                )

            step_name = line.removeprefix("      - name: ")
            if step_name.startswith("Smoke the ") and step_name.endswith(
                " entry point"
            ):
                current_name = step_name
                current_environment = {}
                current_run_lines = []
            else:
                current_name = None
            section = None
            continue

        if current_name is None:
            continue
        if line == "        env:":
            section = "environment"
            continue
        if line == "        run: |":
            section = "run"
            continue
        if section == "environment" and line.startswith("          "):
            name, value = line.strip().split(":", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            current_environment[name] = value
            continue
        if section == "run" and line.startswith("          "):
            current_run_lines.append(line[10:])

    return steps


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

    def test_every_entry_point_defaults_the_embedding_contract(self) -> None:
        """Cold production starts must use the application's documented model."""
        for compose_file in COMPOSE_FILES:
            with self.subTest(compose_file=compose_file):
                backend_environment = compose_config(compose_file)["services"][
                    "backend"
                ]["environment"]

                self.assertEqual(
                    backend_environment.get("EMB_MODEL_NAME"),
                    DEFAULT_EMBEDDING_MODEL,
                )
                self.assertEqual(
                    backend_environment.get("EMB_DIMENSION"),
                    DEFAULT_EMBEDDING_DIMENSION,
                )

    def test_every_entry_point_forwards_embedding_overrides(self) -> None:
        """A host-selected model and dimension must reach the backend process."""
        overrides = {
            "EMB_MODEL_NAME": "sentence-transformers/paraphrase-MiniLM-L3-v2",
            "EMB_DIMENSION": "384",
        }

        for compose_file in COMPOSE_FILES:
            with self.subTest(compose_file=compose_file):
                backend_environment = compose_config(
                    compose_file,
                    environment_overrides=overrides,
                )["services"]["backend"]["environment"]

                self.assertEqual(
                    backend_environment.get("EMB_MODEL_NAME"),
                    "sentence-transformers/paraphrase-MiniLM-L3-v2",
                )
                self.assertEqual(
                    backend_environment.get("EMB_DIMENSION"),
                    "384",
                )

    def test_startup_health_grace_covers_cold_model_bootstrap(self) -> None:
        """Cold model bootstrap may not exhaust backend health retries."""
        root_health = compose_config(COMPOSE_FILES[0])["services"]["backend"][
            "healthcheck"
        ]

        for compose_file in COMPOSE_FILES:
            with self.subTest(compose_file=compose_file):
                health = compose_config(compose_file)["services"]["backend"][
                    "healthcheck"
                ]
                self.assertEqual(health, root_health)

        self.assertIn("start_interval", root_health)
        start_period = duration_seconds(root_health["start_period"])
        start_interval = duration_seconds(root_health["start_interval"])

        self.assertGreater(start_period, OBSERVED_COLD_START_SECONDS)
        self.assertGreaterEqual(start_period, MINIMUM_START_PERIOD_SECONDS)
        self.assertLessEqual(start_interval, 5)

    def test_ci_wait_budget_covers_normalized_health_failure_boundary(self) -> None:
        """CI may not stop before Compose could finish backend health retries."""
        health = compose_config(COMPOSE_FILES[0])["services"]["backend"][
            "healthcheck"
        ]
        start_period = duration_seconds(health["start_period"])
        interval = duration_seconds(health["interval"])
        timeout = duration_seconds(health["timeout"])
        # A probe that starts inside the grace may consume its timeout before
        # the regular retry cadence begins after the grace boundary.
        failure_boundary = (
            start_period + timeout + health["retries"] * (interval + timeout)
        )

        self.assertEqual(
            ci_runtime_wait_timeouts(),
            [EXPECTED_WAIT_TIMEOUT_SECONDS, EXPECTED_WAIT_TIMEOUT_SECONDS],
        )
        self.assertEqual(
            failure_boundary,
            EXPECTED_HEALTH_FAILURE_BOUNDARY_SECONDS,
        )
        self.assertGreaterEqual(EXPECTED_WAIT_TIMEOUT_SECONDS, failure_boundary)

    def test_ci_runtime_smokes_pin_and_verify_the_small_embedding_model(self) -> None:
        """Each fresh CI volume must use and inspect the controlled small model."""
        expected_steps = (
            ("Smoke the root production entry point", COMPOSE_FILES[0]),
            ("Smoke the deploy compatibility entry point", COMPOSE_FILES[1]),
        )
        steps = ci_runtime_smoke_steps()

        self.assertEqual(
            [name for name, _environment, _script in steps],
            [name for name, _compose_file in expected_steps],
        )
        for (name, environment, script), (_expected_name, compose_file) in zip(
            steps,
            expected_steps,
            strict=True,
        ):
            with self.subTest(step=name):
                self.assertEqual(
                    environment.get("EMB_MODEL_NAME"),
                    "sentence-transformers/paraphrase-MiniLM-L3-v2",
                )
                self.assertEqual(environment.get("EMB_DIMENSION"), "384")

                backend_environment = compose_config(
                    compose_file,
                    environment_overrides=environment,
                )["services"]["backend"]["environment"]
                self.assertEqual(
                    backend_environment["EMB_MODEL_NAME"],
                    "sentence-transformers/paraphrase-MiniLM-L3-v2",
                )
                self.assertEqual(backend_environment["EMB_DIMENSION"], "384")

                self.assertIn(
                    'test "$EMB_MODEL_NAME" = '
                    '"sentence-transformers/paraphrase-MiniLM-L3-v2"',
                    script,
                )
                self.assertIn('test "$EMB_DIMENSION" = "384"', script)

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
