"""
Extract quantity callouts from the LEFT half of the sheet (the drawing
itself), as opposed to the BOM table on the right half.

Engineering drawings express quantities in a handful of conventional
patterns, e.g.:

    2-PL p425            -> qty=2,  desc="PL p425"
    4 bolts              -> qty=4,  desc="bolts"
    6 pcs bracket         -> qty=6,  desc="bracket"
    (3) gusset plate      -> qty=3,  desc="gusset plate"  (balloon callout)

We run OCR twice: once for a plain text pass (regex over lines) and once
for word-level data (to recover an approximate bounding box per match).
"""
from __future__ import annotations

import re

from PIL import Image

from app.models.schemas import BBox, DrawingItem
from app.services.ocr_service import (
    group_words_into_lines,
    image_to_words,
    preprocess_for_ocr,
)

# Pattern 1: "2-PL p425" / "2 - bracket"
PATTERN_QTY_DASH_ITEM = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*[-–]\s*([A-Za-z0-9][A-Za-z0-9\s/.\"'#×x]+)$")

# Pattern 2: "4 bolts" (plain qty + description, no unit word)
PATTERN_QTY_ITEM = re.compile(r"^\s*(\d+(?:\.\d+)?)\s+([A-Za-z][A-Za-z0-9\s/.\"'#×x]+)$")

# Pattern 3: "6 pcs bracket" / "4 ea. washer" / "2 nos channel"
PATTERN_QTY_UNIT_ITEM = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*(pcs|pc|ea|nos|no|pk|each|units?)\.?\s+([A-Za-z0-9][A-Za-z0-9\s/.\"'#×x]+)$",
    re.IGNORECASE,
)

# Pattern 4: balloon / leader-line callouts, e.g. "(3) gusset plate" or "3) plate"
PATTERN_BALLOON = re.compile(r"^\s*\(?\s*(\d+(?:\.\d+)?)\s*\)\s*([A-Za-z0-9][A-Za-z0-9\s/.\"'#×x]+)$")

MIN_DESC_LEN = 2
MAX_QTY_SANITY = 100_000


def _clean_desc(desc: str) -> str:
    return re.sub(r"\s+", " ", desc).strip(" .:-")


def _try_match(line_text: str) -> tuple[float, str] | None:
    line_text = line_text.strip()
    if not line_text:
        return None

    for pattern in (PATTERN_QTY_UNIT_ITEM, PATTERN_BALLOON, PATTERN_QTY_DASH_ITEM, PATTERN_QTY_ITEM):
        m = pattern.match(line_text)
        if not m:
            continue
        groups = m.groups()
        qty_str = groups[0]
        desc = groups[-1]
        try:
            qty = float(qty_str)
        except ValueError:
            continue
        desc = _clean_desc(desc)
        if qty <= 0 or qty > MAX_QTY_SANITY or len(desc) < MIN_DESC_LEN:
            continue
        return qty, desc
    return None


def extract_drawing_items(image: Image.Image, page_number: int = 1) -> list[DrawingItem]:
    """OCR the drawing half of the page and pull out quantity callouts."""
    processed = preprocess_for_ocr(image)
    words = image_to_words(processed, psm=6)
    lines = group_words_into_lines(words)

    items: list[DrawingItem] = []
    for line_words in lines:
        line_text = " ".join(w.text for w in line_words)
        match = _try_match(line_text)
        if not match:
            continue
        qty, desc = match

        # Reconstruct a bounding box spanning all words on this line.
        lefts = [w.left for w in line_words]
        tops = [w.top for w in line_words]
        rights = [w.left + w.width for w in line_words]
        bottoms = [w.top + w.height for w in line_words]
        confs = [w.confidence for w in line_words if w.confidence >= 0]
        avg_conf = sum(confs) / len(confs) if confs else 0.5

        items.append(
            DrawingItem(
                description=desc,
                quantity=qty,
                unit=_infer_unit(line_text),
                raw_text=line_text.strip(),
                confidence=round(avg_conf, 3),
                page=page_number,
                bbox=BBox(
                    x=float(min(lefts)),
                    y=float(min(tops)),
                    width=float(max(rights) - min(lefts)),
                    height=float(max(bottoms) - min(tops)),
                ),
            )
        )

    return _dedupe(items)


_UNIT_WORDS = re.compile(r"\b(pcs|pc|ea|each|nos|no|pk|units?)\b", re.IGNORECASE)


def _infer_unit(text: str) -> str:
    m = _UNIT_WORDS.search(text)
    if not m:
        return "ea"
    token = m.group(1).lower()
    if token in ("pc", "pcs"):
        return "pcs"
    if token in ("no", "nos"):
        return "nos"
    if token == "pk":
        return "pk"
    if token in ("unit", "units"):
        return "units"
    return "ea"


def _dedupe(items: list[DrawingItem]) -> list[DrawingItem]:
    """Collapse duplicate lines that OCR occasionally picks up twice
    (e.g. once from a text layer artifact, once from a raster pass)."""
    seen: dict[tuple[str, float], DrawingItem] = {}
    for item in items:
        key = (item.description.lower(), item.quantity)
        if key not in seen or item.confidence > seen[key].confidence:
            seen[key] = item
    return list(seen.values())
