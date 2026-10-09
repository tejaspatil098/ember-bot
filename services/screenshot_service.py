from __future__ import annotations

import hashlib
import io
import logging
import shutil
from dataclasses import dataclass

import imagehash
import pytesseract
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger("referral_bot.screenshots")

ALLOWED_FORMATS = {"JPEG", "PNG"}
MINIMUM_SIZE = (320, 200)


class ScreenshotValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ScreenshotAnalysis:
    sha256: str
    perceptual_hash: str
    ocr_text: str | None
    image_format: str
    width: int
    height: int
    flags: tuple[str, ...]


def calculate_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize_ocr(text: str) -> str:
    return " ".join(text.lower().split())


def _read_ocr(image: Image.Image) -> str | None:
    if not shutil.which("tesseract"):
        return None
    try:
        text = pytesseract.image_to_string(image, timeout=8)
        return _normalize_ocr(text)[:10_000]
    except (pytesseract.TesseractNotFoundError, RuntimeError, OSError) as exc:
        logger.info("OCR unavailable; screenshot routed to manual review: %s", exc)
        return None


def analyze_screenshot(data: bytes, *, max_size_bytes: int) -> ScreenshotAnalysis:
    if not data:
        raise ScreenshotValidationError("The uploaded file is empty.")
    if len(data) > max_size_bytes:
        raise ScreenshotValidationError("The screenshot exceeds the configured size limit.")

    try:
        source = Image.open(io.BytesIO(data))
        image_format = (source.format or "").upper()
        if image_format not in ALLOWED_FORMATS:
            raise ScreenshotValidationError("Only PNG and JPEG screenshots are accepted.")
        source.verify()
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image).convert("RGB")
    except ScreenshotValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ScreenshotValidationError("The image is invalid or corrupted.") from exc

    width, height = image.size
    if width < MINIMUM_SIZE[0] or height < MINIMUM_SIZE[1]:
        raise ScreenshotValidationError("The image is too small to review clearly.")

    flags: list[str] = []
    grayscale = ImageOps.grayscale(image)
    extrema = grayscale.getextrema()
    if extrema[1] - extrema[0] < 3:
        raise ScreenshotValidationError("The image appears blank.")

    ocr_text = _read_ocr(image)
    if not ocr_text:
        flags.append("OCR_UNAVAILABLE_OR_NO_TEXT")
    elif len(ocr_text) < 8:
        flags.append("LITTLE_OR_NO_READABLE_TEXT")

    return ScreenshotAnalysis(
        sha256=calculate_sha256(data),
        perceptual_hash=str(imagehash.phash(image)),
        ocr_text=ocr_text,
        image_format=image_format,
        width=width,
        height=height,
        flags=tuple(flags),
    )


def perceptual_hash_distance(left: str, right: str) -> int:
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except (TypeError, ValueError):
        return 99
