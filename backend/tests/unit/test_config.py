"""Tests that the shipped example configuration is actually usable.

`Settings` forbids keys it does not declare, so an example file that documents a
setting nobody reads does not merely mislead — it stops the process from
starting. These tests exist because both example files are the documented way to
create a `.env` (see AGENTS.md), and one of them could not be loaded at all.
"""
from pathlib import Path

import pytest

from app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_FILES = [
    REPO_ROOT / ".env.example",
    REPO_ROOT / "deploy" / ".env.example",
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


def test_public_registration_defaults_to_development_only():
    """An Internet-facing environment is closed unless enrollment is explicit."""
    assert Settings(app_env="development").allow_public_registration is True
    assert Settings(app_env="production").allow_public_registration is False


def test_production_can_explicitly_enable_public_registration():
    """Operators retain an explicit opt-in for deployments that need signup."""
    settings = Settings(app_env="production", allow_public_registration=True)

    assert settings.allow_public_registration is True
