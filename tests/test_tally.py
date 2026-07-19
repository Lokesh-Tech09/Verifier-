from __future__ import annotations

from app.models.enums import TallyStatus
from app.models.schemas import BOMItem, DrawingItem
from app.services.tally_service import build_tally


def test_build_tally_matching_quantities():
    drawing = [DrawingItem(description="Bolt M8x20", quantity=24, unit="pcs")]
    bom = [BOMItem(description="Bolt M8x20", quantity=24, unit="pcs")]

    results = build_tally(drawing, bom)

    assert len(results) == 1
    assert results[0].status == TallyStatus.MATCH
    assert results[0].difference == 0
    assert results[0].action_required is None


def test_build_tally_mismatch_calculates_difference():
    drawing = [DrawingItem(description="Washer M8", quantity=24, unit="pcs")]
    bom = [BOMItem(description="Washer M8", quantity=20, unit="pcs")]

    results = build_tally(drawing, bom)

    assert results[0].status == TallyStatus.MISMATCH
    assert results[0].difference == 4
    assert results[0].action_required is not None


def test_build_tally_missing_from_bom():
    drawing = [DrawingItem(description="Panel Cover", quantity=2, unit="pcs")]
    bom: list[BOMItem] = []

    results = build_tally(drawing, bom)

    assert results[0].status == TallyStatus.MISSING_BOM
    assert results[0].bom_qty is None
    assert results[0].drawing_qty == 2


def test_build_tally_missing_from_drawing():
    drawing: list[DrawingItem] = []
    bom = [BOMItem(description="Gasket Seal", quantity=2, unit="pcs")]

    results = build_tally(drawing, bom)

    assert results[0].status == TallyStatus.MISSING_DRAWING
    assert results[0].drawing_qty is None
    assert results[0].bom_qty == 2


def test_tally_endpoint_with_explicit_items(client):
    payload = {
        "drawing_items": [
            {"description": "Nut M8", "quantity": 20, "unit": "pcs"},
        ],
        "bom_items": [
            {"description": "Nut M8", "quantity": 20, "unit": "pcs"},
        ],
    }
    resp = client.post("/api/tally", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["matched"] == 1
    assert body["data"]["total_items"] == 1
