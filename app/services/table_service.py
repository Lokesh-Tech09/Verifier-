"""
BOM table detection & parsing from the RIGHT half of the sheet.

Two strategies are attempted, in order:

1. NATIVE TEXT TABLE (fast, high-accuracy path for digital/vector PDFs):
   PyMuPDF's `Page.find_tables()` looks for ruled/whitespace-aligned tables
   directly in the PDF's text layer — no OCR required. Restricted to the
   right half of the page via a clip rectangle.

2. OPENCV GRID + OCR (fallback for scanned/rasterized drawings):
   Detects the table's horizontal and vertical rule lines with
   morphological operations, reconstructs the grid of cells, then OCRs
   each cell individually (`--psm 7`, single line) for clean text.

Column headers ("QTY", "DESCRIPTION", "MATERIAL", ...) are mapped to
semantic roles so the row-parsing logic works regardless of column order.
"""
from __future__ import annotations

import re

import cv2
import numpy as np
from PIL import Image

from app.core.exceptions import TableDetectionError
from app.core.logging import get_logger
from app.models.schemas import BOMItem
from app.services.ocr_service import image_to_text

logger = get_logger(__name__)

# ── header keyword -> semantic column role ──────────────────────────────
_HEADER_MAP: dict[str, tuple[str, ...]] = {
    "qty": ("qty", "quantity", "qty."),
    "description": ("description", "desc", "item", "item description"),
    "piece_mark": ("piece mark", "mark", "assy. mark", "assy mark", "pc mark"),
    "material": ("material", "mat'l", "matl", "spec"),
    "unit": ("unit", "units", "uom"),
}


def _classify_header(cell_text: str) -> str | None:
    t = cell_text.strip().lower().rstrip(".")
    for role, keywords in _HEADER_MAP.items():
        if t in keywords:
            return role
    return None


_FRACTION_RE = re.compile(r"^(\d+)\s+(\d+)\s*/\s*(\d+)$")  # "5 1/4"
_SIMPLE_FRACTION_RE = re.compile(r"^(\d+)\s*/\s*(\d+)$")  # "1/4"


def parse_quantity(raw: str) -> float | None:
    """Parse a BOM quantity cell, including mixed and simple fractions."""
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "")
    if not s:
        return None

    m = _FRACTION_RE.match(s)
    if m:
        whole, num, den = (int(g) for g in m.groups())
        return whole + (num / den if den else 0)

    m = _SIMPLE_FRACTION_RE.match(s)
    if m:
        num, den = (int(g) for g in m.groups())
        return num / den if den else None

    # Strip stray non-numeric characters (units glued to the number, etc.)
    cleaned = re.sub(r"[^0-9.\-]", "", s)
    if not cleaned or cleaned in ("-", "."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _rows_from_native_table(table) -> list[list[str]]:
    rows = []
    for row in table.extract():
        rows.append(["" if c is None else str(c).strip() for c in row])
    return rows


def _extract_native_tables(fitz_page, clip_rect) -> list[list[list[str]]]:
    """Try PyMuPDF's built-in table finder, scoped to the BOM half of the page."""
    tables_out: list[list[list[str]]] = []
    try:
        finder = fitz_page.find_tables(clip=clip_rect)
    except Exception as exc:
        logger.info("Native table finder unavailable/failed: %s", exc)
        return tables_out

    for table in getattr(finder, "tables", []) or []:
        try:
            rows = _rows_from_native_table(table)
        except Exception as exc:
            logger.warning("Failed to extract a native table: %s", exc)
            continue
        if rows:
            tables_out.append(rows)
    return tables_out


def _rows_to_bom_items(rows: list[list[str]], page_number: int) -> list[BOMItem]:
    if not rows:
        return []

    header_row, *data_rows = rows
    col_roles: dict[int, str] = {}
    for idx, cell in enumerate(header_row):
        role = _classify_header(cell)
        if role:
            col_roles[idx] = role

    # If we couldn't map at least a quantity + description column, this
    # probably wasn't a header row (e.g. table with no header). Try a
    # position-based heuristic: assume [qty, piece_mark, description, ...].
    if "qty" not in col_roles.values() or "description" not in col_roles.values():
        col_roles = _fallback_column_roles(header_row)
        data_rows = rows  # header_row wasn't actually a header; reprocess it too

    items: list[BOMItem] = []
    for i, row in enumerate(data_rows):
        values: dict[str, str] = {}
        for idx, cell in enumerate(row):
            role = col_roles.get(idx)
            if role:
                values.setdefault(role, cell)

        desc = (values.get("description") or "").strip()
        qty_raw = values.get("qty")
        qty = parse_quantity(qty_raw) if qty_raw is not None else None

        if not desc or qty is None:
            continue

        items.append(
            BOMItem(
                description=desc,
                quantity=qty,
                unit=(values.get("unit") or "ea").strip() or "ea",
                piece_mark=(values.get("piece_mark") or "").strip() or None,
                material=(values.get("material") or "").strip() or None,
                row_index=i,
                raw_text=" | ".join(c for c in row if c),
            )
        )
    return items


def _fallback_column_roles(sample_row: list[str]) -> dict[int, str]:
    """When no header matches, guess column roles by inspecting cell content:
    the first purely-numeric column is qty, the widest text column is
    description."""
    roles: dict[int, str] = {}
    numeric_idxs = [i for i, c in enumerate(sample_row) if parse_quantity(c) is not None]
    if numeric_idxs:
        roles[numeric_idxs[0]] = "qty"
    text_idxs = [i for i in range(len(sample_row)) if i not in roles]
    if text_idxs:
        # Assume the longest textual cell is the description.
        longest = max(text_idxs, key=lambda i: len(sample_row[i] or ""))
        roles[longest] = "description"
    return roles


# ── OpenCV grid-detection fallback (scanned tables) ─────────────────────
def _pil_to_gray_cv(image: Image.Image) -> np.ndarray:
    arr = np.array(image.convert("L"))
    return arr


def _detect_grid_lines(gray: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    bw = cv2.adaptiveThreshold(
        ~gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2
    )

    h, w = gray.shape
    horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(w // 30, 10), 1))
    vert_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(h // 30, 10)))

    horizontal = cv2.erode(bw, horiz_kernel)
    horizontal = cv2.dilate(horizontal, horiz_kernel)

    vertical = cv2.erode(bw, vert_kernel)
    vertical = cv2.dilate(vertical, vert_kernel)

    return horizontal, vertical


def _grid_to_cells(horizontal: np.ndarray, vertical: np.ndarray) -> list[list[tuple[int, int, int, int]]]:
    mask = cv2.bitwise_or(horizontal, vertical)
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w > 15 and h > 12:
            boxes.append((x, y, w, h))

    if not boxes:
        return []

    # Cluster boxes into rows by y-overlap.
    boxes.sort(key=lambda b: b[1])
    rows: list[list[tuple[int, int, int, int]]] = []
    current_row: list[tuple[int, int, int, int]] = []
    current_y = None
    row_tol = 12

    for box in boxes:
        _, y, _, h = box
        if current_y is None or abs(y - current_y) <= row_tol:
            current_row.append(box)
            current_y = y if current_y is None else current_y
        else:
            rows.append(sorted(current_row, key=lambda b: b[0]))
            current_row = [box]
            current_y = y
    if current_row:
        rows.append(sorted(current_row, key=lambda b: b[0]))

    return rows


def _extract_via_opencv(image: Image.Image) -> list[list[str]]:
    gray = _pil_to_gray_cv(image)
    horizontal, vertical = _detect_grid_lines(gray)
    rows_of_boxes = _grid_to_cells(horizontal, vertical)

    rows: list[list[str]] = []
    for row_boxes in rows_of_boxes:
        row_texts = []
        for (x, y, w, h) in row_boxes:
            pad = 2
            crop = image.crop(
                (max(x - pad, 0), max(y - pad, 0), x + w + pad, y + h + pad)
            )
            text = image_to_text(crop, psm=7).strip()
            row_texts.append(text)
        if any(row_texts):
            rows.append(row_texts)
    return rows


def extract_bom_items(
    image: Image.Image,
    page_number: int = 1,
    fitz_page=None,
    clip_rect=None,
) -> list[BOMItem]:
    """Extract BOM line items from the right half of a sheet.

    Tries the fast native-text table finder first (works great on digital
    PDFs), then falls back to OpenCV grid detection + per-cell OCR for
    scanned/rasterized sheets.
    """
    items: list[BOMItem] = []

    if fitz_page is not None and clip_rect is not None:
        for rows in _extract_native_tables(fitz_page, clip_rect):
            items.extend(_rows_to_bom_items(rows, page_number))

    if not items:
        try:
            rows = _extract_via_opencv(image)
            items = _rows_to_bom_items(rows, page_number)
        except Exception as exc:
            logger.warning("OpenCV table fallback failed: %s", exc)

    if not items:
        raise TableDetectionError(
            "Could not detect a BOM table structure on this page.",
            details={"page": page_number},
        )

    for i, item in enumerate(items):
        item.row_index = i
    return items
