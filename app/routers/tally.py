from __future__ import annotations

from fastapi import APIRouter

from app.models.schemas import BOMItem, DrawingItem, TallyRequest, TallyResponseData
from app.services import job_store, tally_service
from app.utils.response import ok

router = APIRouter(prefix="/api", tags=["tally"])


@router.post("/tally")
async def run_tally(request: TallyRequest) -> dict:
    """Compare drawing quantities against BOM quantities and return a
    per-item verification report.

    Either pass `job_id` to reuse the results from `/api/analyze/{job_id}`,
    or pass `drawing_items`/`bom_items` directly (e.g. after the user has
    hand-edited the extracted rows in the UI).
    """
    if request.job_id and not request.drawing_items and not request.bom_items:
        record = job_store.get_job(request.job_id)
        drawing_items = [DrawingItem(**i) for i in record["drawing_items"]]
        bom_items = [BOMItem(**i) for i in record["bom_items"]]
    else:
        drawing_items = request.drawing_items
        bom_items = request.bom_items

    results = tally_service.build_tally(drawing_items, bom_items)
    summary = tally_service.summarize(results)

    response = TallyResponseData(
        job_id=request.job_id,
        total_items=summary["total_items"],
        matched=summary["matched"],
        mismatched=summary["mismatched"],
        missing=summary["missing"],
        results=results,
    )
    return ok(response)
