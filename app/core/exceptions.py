"""
Custom exception hierarchy for DrawTally.

Every exception carries an HTTP status code, a machine-readable `code`,
a human-readable `message`, and an optional `details` dict. These are
caught by the exception handlers registered in `app.main` and turned
into the standard error envelope:

    {
      "success": false,
      "error": {
        "code": "...",
        "message": "...",
        "details": {...}
      }
    }
"""
from __future__ import annotations

from typing import Any


class DrawTallyError(Exception):
    """Base class for all application-level errors."""

    status_code: int = 500
    code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class PDFUploadError(DrawTallyError):
    """Invalid file, wrong type, too large, etc."""

    status_code = 400
    code = "UPLOAD_INVALID"


class PDFTooLargeError(PDFUploadError):
    status_code = 413
    code = "UPLOAD_TOO_LARGE"


class PDFProcessingError(DrawTallyError):
    """PDF cannot be opened, is corrupted, or has no extractable content."""

    status_code = 422
    code = "PDF_PROCESSING_ERROR"


class OCRError(DrawTallyError):
    """Tesseract failed or the image was unreadable."""

    status_code = 500
    code = "OCR_ERROR"


class TableDetectionError(DrawTallyError):
    """The BOM table structure could not be parsed."""

    status_code = 422
    code = "TABLE_DETECTION_ERROR"


class JobNotFoundError(DrawTallyError):
    """job_id does not exist, or has expired and been cleaned up."""

    status_code = 404
    code = "JOB_NOT_FOUND"


class RateLimitError(DrawTallyError):
    """Too many requests from this client."""

    status_code = 429
    code = "RATE_LIMIT_EXCEEDED"


class ExportError(DrawTallyError):
    """Report export (CSV/JSON/PDF) failed."""

    status_code = 500
    code = "EXPORT_ERROR"
