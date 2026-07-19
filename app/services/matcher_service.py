"""
Smart matching between drawing callouts and BOM line items.

Descriptions rarely match verbatim between a drawing and its BOM (e.g. the
drawing says "PL p425" while the BOM row says "PL 3/8x6x3/16 — p425"), so
we normalize both sides and use fuzzy string matching (rapidfuzz) with a
piece-mark exact-match shortcut.
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from app.core.config import settings
from app.models.schemas import BOMItem, DrawingItem, MatchedPair

# Common structural-steel / fastener abbreviations expanded for matching.
_ABBREVIATIONS = {
    r"\bpl\b": "plate",
    r"\bc(\d)": r"channel \1",
    r"\bw(\d)": r"wideflange \1",
    r"\bl(\d)": r"angle \1",
    r"\bea\b": "each",
    r"\bpcs?\b": "piece",
    r"\bnos?\b": "number",
    r"\bassy\b": "assembly",
    r"\bmatl\b": "material",
    r"\bdia\b": "diameter",
    r"\bbrkt\b": "bracket",
    r"\bgskt\b": "gasket",
}

_SIZE_SPEC_RE = re.compile(
    r"\d+\s*[/\-x×]\s*\d+(\s*[/\-x×]\s*\d+)*|"  # 3/8x6x3/16, 8x20
    r"\d+/\d+"  # 1/4
)

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_description(desc: str, strip_sizes: bool = False) -> str:
    """Lowercase, expand abbreviations, optionally strip dimensional specs,
    and collapse whitespace — producing a comparable "key" string."""
    text = desc.lower().strip()
    for pattern, replacement in _ABBREVIATIONS.items():
        text = re.sub(pattern, replacement, text)
    if strip_sizes:
        text = _SIZE_SPEC_RE.sub(" ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _piece_mark_match(drawing_item: DrawingItem, bom_item: BOMItem) -> bool:
    if not bom_item.piece_mark:
        return False
    mark = bom_item.piece_mark.strip().lower()
    return bool(mark) and mark in drawing_item.description.lower()


def match_items(
    drawing_items: list[DrawingItem],
    bom_items: list[BOMItem],
    threshold: int | None = None,
) -> tuple[list[MatchedPair], list[DrawingItem], list[BOMItem]]:
    """Greedy best-match pairing between drawing callouts and BOM lines.

    Returns (matched_pairs, unmatched_drawing_items, unmatched_bom_items).
    """
    threshold = threshold if threshold is not None else settings.FUZZY_MATCH_THRESHOLD

    remaining_bom = list(bom_items)
    matched: list[MatchedPair] = []
    unmatched_drawing: list[DrawingItem] = []

    for d_item in drawing_items:
        d_key = normalize_description(d_item.description, strip_sizes=True)

        best_idx = -1
        best_score = -1.0

        for idx, b_item in enumerate(remaining_bom):
            if _piece_mark_match(d_item, b_item):
                best_idx, best_score = idx, 100.0
                break

            b_key = normalize_description(b_item.description, strip_sizes=True)
            score = fuzz.token_sort_ratio(d_key, b_key)
            if score > best_score:
                best_idx, best_score = idx, score

        if best_idx >= 0 and best_score >= threshold:
            matched.append(
                MatchedPair(
                    drawing_item=d_item,
                    bom_item=remaining_bom.pop(best_idx),
                    match_score=round(best_score, 1),
                )
            )
        else:
            unmatched_drawing.append(d_item)

    return matched, unmatched_drawing, remaining_bom
