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
