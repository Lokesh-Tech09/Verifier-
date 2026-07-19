from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, File, UploadFile

from app.core.config import settings
from app.core.exceptions import PDFTooLargeError, PDFUploadError
from app.core.logging import get_logger
from app.models.schemas import UploadResponse
from app.services import job_store
from app.utils.file_utils import PDF_MAGIC, sanitize_filename, save_upload
from app.utils.response import ok

router = APIRouter(prefix="/api", tags=["upload"])
logger = get_logger(__name__)

_CHUNK_SIZE = 1024 * 1024  # 1MB


@router.post("/upload")
async def upload_pdf(pdf: UploadFile = File(...)) -> dict:
    """Upload a DrawTally sheet PDF (drawing left half, BOM right half).

    Streams the upload to disk in chunks (rather than reading it all into
    memory at once), rejecting early if it exceeds `UPLOAD_MAX_SIZE` or
    doesn't look like a PDF.
    """
    content_type_ok = (pdf.content_type or "").lower() in (
        "application/pdf",
        "application/x-pdf",
        "binary/octet-stream",
        "application/octet-stream",
    )

    first_chunk = await pdf.read(_CHUNK_SIZE)
    if not first_chunk.startswith(PDF_MAGIC):
        raise PDFUploadError(
            f"Only PDF files are accepted. Received: {pdf.content_type or 'unknown'}",
            details={"received_type": pdf.content_type, "allowed_types": ["application/pdf"]},
        )

    total = len(first_chunk)
    if total > settings.UPLOAD_MAX_SIZE:
        raise PDFTooLargeError(
            f"File exceeds the {settings.UPLOAD_MAX_SIZE // (1024*1024)}MB limit.",
            details={"max_size": settings.UPLOAD_MAX_SIZE},
        )

    job_id = uuid4()
    safe_name = sanitize_filename(pdf.filename or "upload.pdf")
    dest_dir = settings.TEMP_DIR / str(job_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / safe_name

    try:
        with open(dest_path, "wb") as f:
            f.write(first_chunk)
            while True:
                chunk = await pdf.read(_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > settings.UPLOAD_MAX_SIZE:
                    raise PDFTooLargeError(
                        f"File exceeds the {settings.UPLOAD_MAX_SIZE // (1024*1024)}MB limit.",
                        details={"max_size": settings.UPLOAD_MAX_SIZE},
                    )
                f.write(chunk)
    finally:
        await pdf.close()

    if not content_type_ok:
        logger.info("Accepted upload with unusual content-type: %s", pdf.content_type)

    job_store.create_job(job_id, filename=safe_name, file_size=total, file_path=str(dest_path))

    response = UploadResponse(
        job_id=job_id,
        status="processing",
        filename=safe_name,
        file_size=total,
        message="PDF uploaded successfully. Processing started.",
    )
    return ok(response, message=response.message)
