from __future__ import annotations

from uuid import UUID

import fitz
from fastapi import APIRouter

from app.core.exceptions import DrawTallyError, JobNotFoundError, TableDetectionError
from app.core.logging import get_logger
from app.models.schemas import AnalyzeResponseData
from app.services import job_store, pdf_service
from app.services.drawing_service import extract_drawing_items
from app.services.matcher_service import match_items
from app.services.table_service import extract_bom_items
from app.utils.response import ok

router = APIRouter(prefix="/api", tags=["analyze"])
logger = get_logger(__name__)


@router.post("/analyze/{job_id}")
async def analyze_job(job_id: UUID) -> dict:
    """Render the uploaded PDF, OCR the drawing half, detect+parse the BOM
    table on the right half, then fuzzy-match the two sides."""
    record = job_store.get_job(job_id)  # raises JobNotFoundError(404) if missing

    doc: fitz.Document | None = None
    try:
        doc = pdf_service.open_pdf(record["file_path"])

        all_drawing_items = []
        all_bom_items = []
        pages_processed = 0

        for halves in pdf_service.iter_pages(doc):
            pages_processed += 1

            drawing_items = extract_drawing_items(halves.drawing_image, page_number=halves.page_number)
            all_drawing_items.extend(drawing_items)

            # Right-half clip rect in PDF point space (not pixels) for the
            # native table finder.
            clip_rect = fitz.Rect(
                halves.page_width_pt / 2, 0, halves.page_width_pt, halves.page_height_pt
            )
            try:
                bom_items = extract_bom_items(
                    halves.bom_image,
                    page_number=halves.page_number,
                    fitz_page=halves.page,
                    clip_rect=clip_rect,
                )
            except TableDetectionError as exc:
                logger.warning(
                    "No BOM table detected on page %s: %s", halves.page_number, exc.message
                )
                bom_items = []
            all_bom_items.extend(bom_items)

        matched, unmatched_drawing, unmatched_bom = match_items(all_drawing_items, all_bom_items)

        job_store.update_job(
            job_id,
            status="complete",
            drawing_items=[i.model_dump() for i in all_drawing_items],
            bom_items=[i.model_dump() for i in all_bom_items],
            matched_pairs=[p.model_dump() for p in matched],
            unmatched_drawing=[i.model_dump() for i in unmatched_drawing],
            unmatched_bom=[i.model_dump() for i in unmatched_bom],
            pages_processed=pages_processed,
        )

        response = AnalyzeResponseData(
            job_id=job_id,
            status="complete",
            pages_processed=pages_processed,
            drawing_items=all_drawing_items,
            bom_items=all_bom_items,
            matched_pairs=matched,
            unmatched_drawing=unmatched_drawing,
            unmatched_bom=unmatched_bom,
        )
        return ok(response)

    except DrawTallyError:
        job_store.update_job(job_id, status="failed")
        raise
    except Exception as exc:  # pragma: no cover - safety net
        job_store.update_job(job_id, status="failed")
        logger.exception("Unexpected error analyzing job %s", job_id)
        raise
    finally:
        if doc is not None:
            pdf_service.close_pdf(doc)


@router.get("/status/{job_id}")
async def job_status(job_id: UUID) -> dict:
    """Poll a job's current status — useful if analysis is dispatched to a
    background worker instead of run inline."""
    record = job_store.get_job(job_id)
    return ok(
        {
            "job_id": record["job_id"],
            "status": record["status"],
            "filename": record["filename"],
            "pages_processed": record["pages_processed"],
        }
    )
