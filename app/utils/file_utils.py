"""Temp file handling, magic-byte validation, and filename sanitization."""
from __future__ import annotations

import re
import shutil
import time
import uuid
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import PDFTooLargeError, PDFUploadError

# %PDF- is the canonical magic number for PDF files.
PDF_MAGIC = b"%PDF-"

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(filename: str) -> str:
    """Strip path components and unsafe characters from a user-supplied filename."""
    name = Path(filename or "upload.pdf").name  # drops any ../ path traversal
    name = _UNSAFE_CHARS.sub("_", name)
    return name or "upload.pdf"


def validate_pdf_bytes(data: bytes) -> None:
    """Validate the file actually is a PDF by checking magic bytes, not extension."""
    if not data:
        raise PDFUploadError("Uploaded file is empty.")
    if not data.lstrip(b"\x00\r\n\t ")[:1024].startswith(PDF_MAGIC) and PDF_MAGIC not in data[:1024]:
        raise PDFUploadError(
            "Only PDF files are accepted (invalid file signature).",
            details={"expected_magic": "%PDF-"},
        )
    if len(data) > settings.UPLOAD_MAX_SIZE:
        raise PDFTooLargeError(
            f"File exceeds the {settings.UPLOAD_MAX_SIZE // (1024*1024)}MB limit.",
            details={"file_size": len(data), "max_size": settings.UPLOAD_MAX_SIZE},
        )


def job_dir(job_id: str | uuid.UUID) -> Path:
    d = settings.TEMP_DIR / str(job_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_upload(job_id: str | uuid.UUID, filename: str, data: bytes) -> Path:
    d = job_dir(job_id)
    safe_name = sanitize_filename(filename)
    path = d / safe_name
    path.write_bytes(data)
    return path


def cleanup_expired_jobs(ttl_seconds: int | None = None) -> int:
    """Delete job directories older than TTL. Returns number removed."""
    ttl = ttl_seconds if ttl_seconds is not None else settings.TEMP_FILE_TTL
    removed = 0
    now = time.time()
    if not settings.TEMP_DIR.exists():
        return 0
    for child in settings.TEMP_DIR.iterdir():
        try:
            if child.is_dir() and (now - child.stat().st_mtime) > ttl:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        except FileNotFoundError:
            continue
    return removed


def cleanup_job(job_id: str | uuid.UUID) -> None:
    d = settings.TEMP_DIR / str(job_id)
    shutil.rmtree(d, ignore_errors=True)
