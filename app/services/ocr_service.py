"""
OCR text extraction from images.

Handles preprocessing (grayscale, adaptive threshold, denoise, deskew) and
wraps `pytesseract` for both plain-text and word-level (bbox + confidence)
extraction.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import pytesseract
from PIL import Image
from pytesseract import Output

from app.core.config import settings
from app.core.exceptions import OCRError
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class OCRWord:
    text: str
    confidence: float  # 0-1
    left: int
    top: int
    width: int
    height: int
    line_num: int
    block_num: int
    par_num: int = 0


def _pil_to_cv(image: Image.Image) -> np.ndarray:
    arr = np.array(image.convert("RGB"))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def _cv_to_pil(mat: np.ndarray) -> Image.Image:
    if len(mat.shape) == 2:
        return Image.fromarray(mat)
    return Image.fromarray(cv2.cvtColor(mat, cv2.COLOR_BGR2RGB))


def _deskew(gray: np.ndarray) -> np.ndarray:
    """Estimate and correct small rotations using the minAreaRect of text pixels."""
    coords = np.column_stack(np.where(gray < 250))
    if coords.shape[0] < 20:
        return gray
    angle = cv2.minAreaRect(coords.astype(np.float32))[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    # Only correct small skews; large angles usually mean minAreaRect picked
    # up something other than text orientation.
    if abs(angle) < 0.5 or abs(angle) > 15:
        return gray
    (h, w) = gray.shape[:2]
    center = (w // 2, h // 2)
    rot_mat = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(
        gray, rot_mat, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def preprocess_for_ocr(image: Image.Image) -> Image.Image:
    """Grayscale -> denoise -> adaptive threshold -> deskew, tuned for scanned
    engineering drawings and printed BOM tables."""
    try:
        mat = _pil_to_cv(image)
        gray = cv2.cvtColor(mat, cv2.COLOR_BGR2GRAY)
        denoised = cv2.bilateralFilter(gray, d=7, sigmaColor=55, sigmaSpace=55)
        thresh = cv2.adaptiveThreshold(
            denoised,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=31,
            C=11,
        )
        deskewed = _deskew(thresh)
        return _cv_to_pil(deskewed)
    except Exception as exc:
        logger.warning("Preprocessing failed, falling back to raw image: %s", exc)
        return image


def image_to_text(image: Image.Image, psm: int | None = None) -> str:
    psm = psm if psm is not None else settings.OCR_PSM
    config = f"--psm {psm}"
    try:
        return pytesseract.image_to_string(image, lang=settings.OCR_LANG, config=config)
    except pytesseract.TesseractNotFoundError as exc:
        raise OCRError("Tesseract binary not found on the server.") from exc
    except Exception as exc:
        raise OCRError(f"OCR text extraction failed: {exc}") from exc


def image_to_words(image: Image.Image, psm: int | None = None) -> list[OCRWord]:
    """Word-level OCR with bounding boxes and confidence, used for both the
    drawing-callout regex pass and the BOM row/column clustering pass."""
    psm = psm if psm is not None else settings.OCR_PSM
    config = f"--psm {psm}"
    try:
        data = pytesseract.image_to_data(
            image, lang=settings.OCR_LANG, config=config, output_type=Output.DICT
        )
    except pytesseract.TesseractNotFoundError as exc:
        raise OCRError("Tesseract binary not found on the server.") from exc
    except Exception as exc:
        raise OCRError(f"OCR word extraction failed: {exc}") from exc

    words: list[OCRWord] = []
    n = len(data.get("text", []))
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except (ValueError, TypeError):
            conf = -1.0
        if conf < 0:
            continue
        words.append(
            OCRWord(
                text=text,
                confidence=conf / 100.0,
                left=int(data["left"][i]),
                top=int(data["top"][i]),
                width=int(data["width"][i]),
                height=int(data["height"][i]),
                line_num=int(data["line_num"][i]),
                block_num=int(data["block_num"][i]),
                par_num=int(data.get("par_num", [0] * n)[i]) if data.get("par_num") else 0,
            )
        )
    return words


def group_words_into_lines(words: list[OCRWord]) -> list[list[OCRWord]]:
    """Group OCR words into visual lines using (block_num, par_num, line_num),
    then sort each line left-to-right.

    Tesseract's `line_num` restarts within each paragraph, so grouping by
    `(block_num, line_num)` alone incorrectly merges unrelated lines from
    different paragraphs that happen to share a line number. Including
    `par_num` disambiguates them.
    """
    lines: dict[tuple[int, int, int], list[OCRWord]] = {}
    for w in words:
        key = (w.block_num, w.par_num, w.line_num)
        lines.setdefault(key, []).append(w)

    ordered_keys = sorted(lines.keys(), key=lambda k: min(w.top for w in lines[k]))
    return [sorted(lines[k], key=lambda w: w.left) for k in ordered_keys]
