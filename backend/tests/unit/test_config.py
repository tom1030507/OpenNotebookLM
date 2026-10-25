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


def test_citation_check_defaults_to_the_calibrated_threshold_and_can_be_disabled(monkeypatch):
    monkeypatch.delenv("CITATION_CHECK_ENABLED", raising=False)
    monkeypatch.delenv("CITATION_CHECK_THRESHOLD", raising=False)

    defaults = Settings(_env_file=None)

    assert defaults.citation_check_enabled is True
    assert defaults.citation_check_threshold == 0.83
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "CITATION_CHECK_ENABLED=true" in example
    assert "CITATION_CHECK_THRESHOLD=0.83" in example

    monkeypatch.setenv("CITATION_CHECK_ENABLED", "false")
    monkeypatch.setenv("CITATION_CHECK_THRESHOLD", "0.91")
    overrides = Settings(_env_file=None)
    assert overrides.citation_check_enabled is False
    assert overrides.citation_check_threshold == 0.91


def test_allowed_upload_types_match_the_documented_example():
    """The route allowlist and the tracked environment example stay aligned."""
    expected = [
        "pdf", "txt", "md", "docx", "pptx", "xlsx", "epub",
        "png", "jpg", "jpeg", "webp",
        "mp3", "m4a", "wav", "ogg", "webm", "flac",
    ]
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")

    assert Settings(_env_file=None).allowed_file_types_list == expected
    assert "ALLOWED_FILE_TYPES=" + ",".join(expected) in example
    compose = yaml.safe_load(
        (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    )
    assert compose["services"]["backend"]["environment"]["ALLOWED_FILE_TYPES"] == (
        "${ALLOWED_FILE_TYPES:-" + ",".join(expected) + "}"
    )


def test_audio_transcription_duration_defaults_and_environment_override(monkeypatch):
    """Uploaded audio inherits the YouTube 30-minute safety default."""
    monkeypatch.delenv("AUDIO_MAX_DURATION_SECONDS", raising=False)
    assert Settings(_env_file=None).audio_max_duration_seconds == 1800

    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "AUDIO_MAX_DURATION_SECONDS=1800" in example
    compose = yaml.safe_load(
        (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    )
    assert compose["services"]["backend"]["environment"][
        "AUDIO_MAX_DURATION_SECONDS"
    ] == "${AUDIO_MAX_DURATION_SECONDS:-1800}"

    monkeypatch.setenv("AUDIO_MAX_DURATION_SECONDS", "900")
    assert Settings(_env_file=None).audio_max_duration_seconds == 900


def test_ocr_is_enabled_and_models_cache_under_the_volume(monkeypatch):
    """OCR defaults on and its model cache uses the persistent models volume."""
    monkeypatch.delenv("OCR_ENABLED", raising=False)
    monkeypatch.delenv("OCR_MODEL_CACHE_DIR", raising=False)

    settings = Settings(_env_file=None)

    assert settings.ocr_enabled is True
    assert settings.ocr_model_cache_dir == "./models/rapidocr"

    monkeypatch.setenv("OCR_ENABLED", "false")
    monkeypatch.setenv("OCR_MODEL_CACHE_DIR", "/cache/ocr")
    overrides = Settings(_env_file=None)

    assert overrides.ocr_enabled is False
    assert overrides.ocr_model_cache_dir == "/cache/ocr"

    compose = yaml.safe_load(
        (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    )
    backend_environment = compose["services"]["backend"]["environment"]
    assert backend_environment["OCR_ENABLED"] == "${OCR_ENABLED:-true}"
    assert backend_environment["OCR_MODEL_CACHE_DIR"] == (
        "${OCR_MODEL_CACHE_DIR:-/app/models/rapidocr}"
    )
    assert backend_environment["ALLOWED_FILE_TYPES"] == (
        "${ALLOWED_FILE_TYPES:-pdf,txt,md,docx,pptx,xlsx,epub,png,jpg,jpeg,webp,"
        "mp3,m4a,wav,ogg,webm,flac}"
    )


@pytest.mark.parametrize("chunk_size", [0, -1])
def test_non_positive_chunk_size_is_rejected_during_config_parse(chunk_size):
    """Invalid chunk geometry cannot survive until a worker starts ingesting."""
    with pytest.raises(ValidationError):
        Settings(chunk_size=chunk_size)


@pytest.mark.parametrize("concurrency", [0, 17])
def test_ingestion_worker_concurrency_is_bounded(concurrency):
    """Configuration cannot create zero or an excessive number of workers.

    Args:
        concurrency: Invalid worker count under test.

    Returns:
        None.
    """
    with pytest.raises(ValidationError):
        Settings(ingestion_worker_concurrency=concurrency)


def test_both_compose_entry_points_forward_ingestion_worker_concurrency():
    """The compatibility Compose file inherits the canonical worker setting.

    Args:
        None.

    Returns:
        None.
    """
    root_compose = yaml.safe_load(
        (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    )
    backend_environment = root_compose["services"]["backend"]["environment"]
    assert backend_environment["INGESTION_WORKER_CONCURRENCY"] == (
        "${INGESTION_WORKER_CONCURRENCY:-1}"
    )

    compatibility_compose = yaml.safe_load(
        (REPO_ROOT / "deploy" / "docker-compose.yml").read_text(
            encoding="utf-8"
        )
    )
    assert compatibility_compose["include"] == [{
        "path": "../docker-compose.yml",
        "project_directory": "..",
    }]


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


def test_youtube_whisper_defaults(monkeypatch):
    """Captionless videos use the bounded local fallback by default."""
    for variable in (
        "YT_WHISPER_FALLBACK_ENABLED",
        "YT_WHISPER_MODEL",
        "YT_MAX_DURATION_SECONDS",
        "YT_WHISPER_CACHE_DIR",
    ):
        monkeypatch.delenv(variable, raising=False)

    settings = Settings(_env_file=None)

    assert settings.yt_whisper_fallback_enabled is True
    assert settings.yt_whisper_model == "base"
    assert settings.yt_max_duration_seconds == 1800
    assert settings.yt_whisper_cache_dir == "./models/whisper"


def test_youtube_whisper_environment_overrides(monkeypatch):
    """Deployments can tune or disable local audio transcription."""
    monkeypatch.setenv("YT_WHISPER_FALLBACK_ENABLED", "false")
    monkeypatch.setenv("YT_WHISPER_MODEL", "small")
    monkeypatch.setenv("YT_MAX_DURATION_SECONDS", "900")
    monkeypatch.setenv("YT_WHISPER_CACHE_DIR", "./cache/whisper")

    settings = Settings(_env_file=None)

    assert settings.yt_whisper_fallback_enabled is False
    assert settings.yt_whisper_model == "small"
    assert settings.yt_max_duration_seconds == 900
    assert settings.yt_whisper_cache_dir == "./cache/whisper"


def test_audio_overview_synthesis_defaults_on_and_can_be_disabled(monkeypatch):
    """The documented switch controls only the generated local audio path."""
    for variable in ("AUDIO_OVERVIEW_TTS_ENABLED",):
        monkeypatch.delenv(variable, raising=False)

    assert Settings(_env_file=None).audio_overview_tts_enabled is True
    monkeypatch.setenv("AUDIO_OVERVIEW_TTS_ENABLED", "false")
    assert Settings(_env_file=None).audio_overview_tts_enabled is False
