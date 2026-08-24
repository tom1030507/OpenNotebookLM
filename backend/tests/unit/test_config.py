"""Tests that the shipped example configuration is actually usable.

`Settings` forbids keys it does not declare, so an example file that documents a
setting nobody reads does not merely mislead — it stops the process from
starting. This test covers the root example, the single canonical deployment
configuration shipped by the repository.
"""
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_FILES = [
    REPO_ROOT / ".env.example",
]


@pytest.mark.parametrize(
    "example", EXAMPLE_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_example_env_file_loads_into_settings(example):
    """Copying an example file to `.env` must not break start-up."""
    assert example.exists(), f"missing example file: {example}"

    # Raises ValidationError on any key Settings does not declare.
    Settings(_env_file=example)


def test_a_blank_optional_number_reads_as_unset(tmp_path):
    """The natural way to leave an optional setting out is to leave it blank.

    For a string field pydantic accepts that already. For a number it is a
    validation error, and `.env.example` documents two optional numbers — so a
    copied example file would stop the process from starting.
    """
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_MAX_OUTPUT_TOKENS=\nLLM_MAX_REQUEST_TOKENS=   \n", encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.llm_max_output_tokens is None
    assert settings.llm_max_request_tokens is None


def test_a_set_optional_number_is_still_read(tmp_path):
    """Tolerating a blank must not mean ignoring a value."""
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_MAX_REQUEST_TOKENS=8000\n", encoding="utf-8")

    assert Settings(_env_file=env_file).llm_max_request_tokens == 8000


@pytest.mark.parametrize("chunk_size", [0, -1])
def test_non_positive_chunk_size_is_rejected_during_config_parse(chunk_size):
    """Invalid chunk geometry cannot survive until a worker starts ingesting."""
    with pytest.raises(ValidationError):
        Settings(chunk_size=chunk_size)


def test_public_registration_defaults_to_development_only():
    """An Internet-facing environment is closed unless enrollment is explicit."""
    assert Settings(app_env="development").allow_public_registration is True
    assert Settings(app_env="production").allow_public_registration is False


def test_production_can_explicitly_enable_public_registration():
    """Operators retain an explicit opt-in for deployments that need signup."""
    settings = Settings(app_env="production", allow_public_registration=True)

    assert settings.allow_public_registration is True


def test_compose_redis_has_finite_memory_without_public_port() -> None:
    """The optional cache is bounded, internal, and fully disposable."""
    compose_path = REPO_ROOT / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    redis_service = compose["services"]["redis"]
    command_parts = redis_service["command"]
    command = " ".join(command_parts)

    assert "ports" not in redis_service
    assert "--maxmemory" in command
    assert "${REDIS_MAXMEMORY:-256mb}" in command
    assert "--maxmemory-policy allkeys-lru" in command
    assert "--appendonly no" in command
    save_index = command_parts.index("--save")
    assert command_parts[save_index + 1] == ""
    assert "volumes" not in redis_service
    assert "redis_data" not in compose.get("volumes", {})

    settings = Settings(_env_file=REPO_ROOT / ".env.example")
    assert settings.redis_maxmemory == "256mb"
