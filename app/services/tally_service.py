"""
Quantity comparison logic: reconciles drawing callouts against BOM lines
and produces a per-item verification report.
"""
from __future__ import annotations

from app.models.enums import Severity, TallyStatus
from app.models.schemas import BOMItem, DrawingItem, TallyResult
from app.services.matcher_service import match_items


def _severity_for(status: TallyStatus, diff: float) -> Severity:
    if status == TallyStatus.MATCH:
        return Severity.NONE
    if status == TallyStatus.MISMATCH:
        return Severity.HIGH if abs(diff) > 1 else Severity.MEDIUM
    # missing-drawing / missing-bom
    return Severity.MEDIUM


def _action_for(status: TallyStatus, desc: str, drawing_qty, bom_qty) -> str | None:
    if status == TallyStatus.MATCH:
        return None
    if status == TallyStatus.MISMATCH:
        return (
            f"BOM lists {bom_qty:g} but drawing shows {drawing_qty:g}. "
            f"Update the BOM quantity to {drawing_qty:g}, or verify the drawing is correct."
        )
    if status == TallyStatus.MISSING_BOM:
        return f"Item appears in drawing (qty {drawing_qty:g}) but is missing from the BOM. Add it to the BOM."
    if status == TallyStatus.MISSING_DRAWING:
        return f"Item appears in BOM (qty {bom_qty:g}) but has no matching callout on the drawing. Verify it's still required."
    return None


def build_tally(
    drawing_items: list[DrawingItem], bom_items: list[BOMItem]
) -> list[TallyResult]:
    matched, unmatched_drawing, unmatched_bom = match_items(drawing_items, bom_items)

    results: list[TallyResult] = []

    for pair in matched:
        d, b = pair.drawing_item, pair.bom_item
        diff = d.quantity - b.quantity
        status = TallyStatus.MATCH if diff == 0 else TallyStatus.MISMATCH
        results.append(
            TallyResult(
                description=d.description,
                drawing_qty=d.quantity,
                bom_qty=b.quantity,
                difference=diff,
                status=status,
                draw_unit=d.unit,
                bom_unit=b.unit,
                action_required=_action_for(status, d.description, d.quantity, b.quantity),
                severity=_severity_for(status, diff),
            )
        )

    for d in unmatched_drawing:
        results.append(
            TallyResult(
                description=d.description,
                drawing_qty=d.quantity,
                bom_qty=None,
                difference=d.quantity,
                status=TallyStatus.MISSING_BOM,
                draw_unit=d.unit,
                bom_unit="ea",
                action_required=_action_for(TallyStatus.MISSING_BOM, d.description, d.quantity, None),
                severity=_severity_for(TallyStatus.MISSING_BOM, d.quantity),
            )
        )

    for b in unmatched_bom:
        results.append(
            TallyResult(
                description=b.description,
                drawing_qty=None,
                bom_qty=b.quantity,
                difference=-b.quantity,
                status=TallyStatus.MISSING_DRAWING,
                draw_unit="ea",
                bom_unit=b.unit,
                action_required=_action_for(TallyStatus.MISSING_DRAWING, b.description, None, b.quantity),
                severity=_severity_for(TallyStatus.MISSING_DRAWING, b.quantity),
            )
        )

    return results


def summarize(results: list[TallyResult]) -> dict[str, int]:
    return {
        "total_items": len(results),
        "matched": sum(1 for r in results if r.status == TallyStatus.MATCH),
        "mismatched": sum(1 for r in results if r.status == TallyStatus.MISMATCH),
        "missing": sum(
            1 for r in results if r.status in (TallyStatus.MISSING_BOM, TallyStatus.MISSING_DRAWING)
        ),
    }
