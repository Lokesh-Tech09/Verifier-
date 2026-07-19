"""
PDF rendering, splitting, and cleanup.

DrawTally's source PDFs are a single sheet with the engineering drawing on
the left half and the BOM table on the right half. This service opens the
PDF with PyMuPDF, rasterizes each page at a print-quality DPI, and splits
each page image down the middle into a `drawing` half and a `bom` half.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

from app.core.config import settings
from app.core.exceptions import PDFProcessingError
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PageHalves:
    page_number: int  # 1-indexed
    drawing_image: Image.Image
    bom_image: Image.Image
    page: "fitz.Page"
    page_width_pt: float
    page_height_pt: float


def open_pdf(path: str | Path) -> fitz.Document:
    try:
        doc = fitz.open(str(path))
    except Exception as exc:  # pragma: no cover - fitz raises varied errors
        raise PDFProcessingError(f"Could not open PDF: {exc}") from exc

    if doc.page_count == 0:
        raise PDFProcessingError("PDF contains no pages.")
    return doc


def render_page_halves(doc: fitz.Document, page_index: int, dpi: int | None = None) -> PageHalves:
    """Render a single page and split it vertically at 50% width.

    Returns the LEFT half as the drawing image and the RIGHT half as the
    BOM image, per DrawTally's standard sheet layout.
    """
    dpi = dpi or settings.OCR_DPI
    try:
        page = doc.load_page(page_index)
    except Exception as exc:
        raise PDFProcessingError(f"Could not load page {page_index + 1}: {exc}") from exc

    zoom = dpi / 72.0  # PDF points are 1/72 inch
    matrix = fitz.Matrix(zoom, zoom)

    try:
        pix = page.get_pixmap(matrix=matrix, alpha=False)
    except Exception as exc:
        raise PDFProcessingError(f"Could not render page {page_index + 1}: {exc}") from exc

    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    mid = pix.width // 2
    drawing_img = img.crop((0, 0, mid, pix.height))
    bom_img = img.crop((mid, 0, pix.width, pix.height))

    return PageHalves(
        page_number=page_index + 1,
        drawing_image=drawing_img,
        bom_image=bom_img,
        page=page,
        page_width_pt=page.rect.width,
        page_height_pt=page.rect.height,
    )


def iter_pages(doc: fitz.Document, dpi: int | None = None):
    for i in range(doc.page_count):
        yield render_page_halves(doc, i, dpi=dpi)


def close_pdf(doc: fitz.Document) -> None:
    try:
        doc.close()
    except Exception:  # pragma: no cover
        pass
