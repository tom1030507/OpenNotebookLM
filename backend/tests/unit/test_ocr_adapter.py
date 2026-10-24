"""Tests for bounded, local image OCR."""
import os
from pathlib import Path
from types import SimpleNamespace
import warnings

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import pytest

from app.adapters.ocr import InvalidImageError, OCRAdapter


def _write_image(path: Path, size=(160, 100)) -> None:
    """Write a small RGB image fixture."""
    Image.new("RGB", size, "white").save(path)


class _LayoutEngine:
    """Return two lines in reverse geometric order to test normalization."""

    def __init__(self):
        self.calls = 0

    def __call__(self, image):
        self.calls += 1
        assert image.shape == (100, 160, 3)
        return SimpleNamespace(
            txts=("Lower line", "Upper line"),
            boxes=np.asarray(
                [
                    [[10, 50], [100, 50], [100, 65], [10, 65]],
                    [[10, 10], [100, 10], [100, 25], [10, 25]],
                ],
                dtype=np.float32,
            ),
        )


def test_engine_is_lazy_and_loaded_once_per_cache_directory(tmp_path):
    """Validation avoids model load and adapters share one cached engine."""
    image_path = tmp_path / "report.png"
    _write_image(image_path)
    engine = _LayoutEngine()
    loads = []

    def load_engine(cache_dir):
        loads.append(cache_dir)
        return engine

    first = OCRAdapter(str(tmp_path / "models"), engine_loader=load_engine)
    second = OCRAdapter(str(tmp_path / "models"), engine_loader=load_engine)

    first.validate_image_file(str(image_path))
    assert loads == []

    first.extract_text_from_image(str(image_path), "report.png")
    second.extract_text_from_image(str(image_path), "report.png")

    assert loads == [str(tmp_path / "models")]
    assert engine.calls == 2


def test_image_text_has_filename_heading_and_reading_order(tmp_path):
    """OCR output starts with the source name and orders lines top to bottom."""
    image_path = tmp_path / "report.png"
    _write_image(image_path)
    engine = _LayoutEngine()
    adapter = OCRAdapter(
        str(tmp_path / "models"),
        engine_loader=lambda _cache_dir: engine,
    )

    result = adapter.extract_text_from_image(str(image_path), "report.png")

    assert result["text"] == "# report.png\n\nUpper line\nLower line"
    assert result["num_pages"] == 1
    assert result["pages"][0]["text"] == "Upper line\nLower line"


def test_invalid_image_is_rejected_before_engine_load(tmp_path):
    """Malformed uploaded bytes fail validation without loading OCR models."""
    image_path = tmp_path / "broken.png"
    image_path.write_bytes(b"not a PNG image")
    loads = []
    adapter = OCRAdapter(
        str(tmp_path / "models"),
        engine_loader=lambda cache_dir: loads.append(cache_dir),
    )

    with pytest.raises(InvalidImageError, match="valid image"):
        adapter.validate_image_file(str(image_path))

    assert loads == []


def test_image_over_pixel_cap_is_rejected_before_engine_load(tmp_path, monkeypatch):
    """A tiny compressed header cannot trigger a huge decoded image allocation."""

    class OversizedImage:
        size = (40_000_001, 1)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def load(self):
            pytest.fail("oversized pixels must be rejected before Image.load")

    image_path = tmp_path / "oversized.png"
    image_path.write_bytes(b"compressed image header")
    monkeypatch.setattr(Image, "open", lambda *_args, **_kwargs: OversizedImage())
    loads = []
    adapter = OCRAdapter(
        str(tmp_path / "models"),
        engine_loader=lambda cache_dir: loads.append(cache_dir),
    )

    with pytest.raises(InvalidImageError, match="40,000,000 pixels"):
        adapter.validate_image_file(str(image_path))

    assert loads == []


def test_pillow_decompression_bomb_warning_is_rejected(tmp_path, monkeypatch):
    """Pillow's warning remains an error at the upload boundary."""

    class BombWarningImage:
        size = (100, 100)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def verify(self):
            return None

    image_path = tmp_path / "bomb.png"
    image_path.write_bytes(b"image bytes")

    def open_bomb(*_args, **_kwargs):
        warnings.warn(
            "Decompression bomb test warning",
            Image.DecompressionBombWarning,
        )
        return BombWarningImage()

    monkeypatch.setattr(Image, "open", open_bomb)
    adapter = OCRAdapter(str(tmp_path / "models"), engine_loader=lambda _path: None)

    with pytest.raises(InvalidImageError, match="valid image"):
        adapter.validate_image_file(str(image_path))


@pytest.mark.ocr_real
@pytest.mark.skipif(os.getenv("RUN_REAL_OCR") != "1", reason="set RUN_REAL_OCR=1 to download models")
def test_real_rapidocr_recognizes_printed_text(tmp_path):
    """A marked CPU integration test exercises RapidOCR against printed text."""
    image_path = tmp_path / "printed.png"
    image = Image.new("RGB", (1000, 140), "white")
    drawing = ImageDraw.Draw(image)
    drawing.text(
        (30, 30),
        "OpenNotebook OCR 98",
        fill="black",
        font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 48),
    )
    image.save(image_path)
    adapter = OCRAdapter(str(tmp_path / "models"))

    result = adapter.extract_text_from_image(str(image_path), "printed.png")

    assert "OCR" in result["text"].upper()
    assert "98" in result["text"]
