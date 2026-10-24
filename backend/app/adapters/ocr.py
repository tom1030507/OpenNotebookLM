"""Bounded local OCR for uploaded images and rendered PDF pages."""
from pathlib import Path
import re
import threading
from typing import Any, Callable, Dict, Optional
import warnings

import numpy as np


# Pillow and NumPy may hold multiple decoded RGB copies at once, so cap pixels
# before an uploaded image can consume unbounded worker memory.
MAX_OCR_IMAGE_PIXELS = 40_000_000
_ENGINE_LOCK = threading.Lock()
_ENGINES: Dict[tuple[str, int], Any] = {}


class InvalidImageError(ValueError):
    """Raised when an image cannot be decoded within the configured bound."""


def _load_rapidocr(cache_dir: str) -> Any:
    """Create a CPU RapidOCR engine that stores model files in the volume.

    Args:
        cache_dir: Persistent directory for model files downloaded on first use.

    Returns:
        A configured RapidOCR engine.
    """
    from rapidocr import RapidOCR

    return RapidOCR(params={
        "Global.model_root_dir": cache_dir,
        "Global.use_cls": False,
        "EngineConfig.onnxruntime.use_cuda": False,
    })


class OCRAdapter:
    """Validate local images and extract searchable text with CPU OCR."""

    def __init__(
        self,
        cache_dir: str,
        engine_loader: Optional[Callable[[str], Any]] = None,
        max_image_pixels: int = MAX_OCR_IMAGE_PIXELS,
    ) -> None:
        """Configure OCR without loading models until the first recognition.

        Args:
            cache_dir: Persistent model directory mounted under `/app/models`.
            engine_loader: Optional lazy engine factory used by tests.
            max_image_pixels: Maximum decoded image pixels accepted.

        Returns:
            None.
        """
        self.cache_dir = str(Path(cache_dir).expanduser().resolve())
        self.engine_loader = engine_loader or _load_rapidocr
        self.max_image_pixels = max_image_pixels

    def validate_image_file(self, file_path: str) -> None:
        """Decode an image once to reject corrupt or oversized uploads early.

        Args:
            file_path: Local path to an uploaded image.

        Returns:
            None.

        Raises:
            InvalidImageError: If the image is malformed or exceeds the cap.
        """
        image = self._read_image(file_path)
        image.close()

    def recognize_image(self, image: np.ndarray) -> str:
        """Recognize and order visible text in an RGB image array.

        Args:
            image: Decoded RGB image pixels.

        Returns:
            Recognized lines ordered from top to bottom, then left to right.
        """
        if image.ndim < 2 or image.shape[0] * image.shape[1] > self.max_image_pixels:
            raise InvalidImageError(
                "The image exceeds the maximum of %s pixels"
                % format(self.max_image_pixels, ",")
            )

        engine = self._get_engine()
        result = engine(image)
        texts = getattr(result, "txts", None)
        if texts is None:
            return ""

        text_values = list(texts)
        boxes = getattr(result, "boxes", None)
        ordered = []
        for index, text in enumerate(text_values):
            cleaned = str(text or "").strip()
            if not cleaned:
                continue
            top = float(index)
            left = 0.0
            if boxes is not None and index < len(boxes):
                try:
                    box = np.asarray(boxes[index], dtype=float)
                    top = float(np.mean(box[:, 1]))
                    left = float(np.mean(box[:, 0]))
                except (IndexError, TypeError, ValueError):
                    pass
            ordered.append((top, left, index, cleaned))

        ordered.sort(key=lambda item: (item[0], item[1], item[2]))
        return "\n".join(item[3] for item in ordered)

    def extract_text_from_image(
        self,
        file_path: str,
        filename: str,
    ) -> Dict[str, Any]:
        """Extract searchable text and source metadata from an image file.

        Args:
            file_path: Local path to an uploaded image.
            filename: Original source filename shown in extracted content.

        Returns:
            Text, page information, and OCR metadata for document indexing.
        """
        image = self._read_image(file_path)
        try:
            recognized_text = self.recognize_image(
                np.asarray(image, dtype=np.uint8).copy()
            )
        finally:
            image.close()

        safe_filename = Path(filename.replace("\\", "/")).name
        safe_filename = re.sub(r"[\r\n]+", " ", safe_filename).strip()
        if not safe_filename:
            safe_filename = "image"

        return {
            "text": "# %s\n\n%s" % (safe_filename, recognized_text),
            "pages": [{
                "page_num": 1,
                "text": recognized_text,
                "char_count": len(recognized_text),
            }],
            "num_pages": 1,
            "metadata": {
                "ocr_engine": "RapidOCR",
                "ocr_pages": 1,
            },
        }

    def _read_image(self, file_path: str) -> Any:
        """Load a bounded image with decompression-bomb warnings enabled."""
        from PIL import Image, ImageOps, UnidentifiedImageError

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(file_path) as source:
                    width, height = source.size
                    if width * height > self.max_image_pixels:
                        raise InvalidImageError(
                            "The image exceeds the maximum of %s pixels"
                            % format(self.max_image_pixels, ",")
                        )
                    oriented = ImageOps.exif_transpose(source)
                    oriented.load()
                    return oriented.convert("RGB")
        except InvalidImageError:
            raise
        except (
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
            UnidentifiedImageError,
            OSError,
            SyntaxError,
            ValueError,
        ) as error:
            raise InvalidImageError(
                "The uploaded file is not a valid image or exceeds the image safety limits"
            ) from error

    def _get_engine(self) -> Any:
        """Load and share a CPU engine once for this model cache and factory."""
        key = (self.cache_dir, id(self.engine_loader))
        with _ENGINE_LOCK:
            if key not in _ENGINES:
                Path(self.cache_dir).mkdir(parents=True, exist_ok=True)
                _ENGINES[key] = self.engine_loader(self.cache_dir)
            return _ENGINES[key]
