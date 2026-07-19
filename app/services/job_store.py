"""
In-memory job store.

Keyed by job_id (UUID). Holds upload metadata plus, once analysis has run,
the extracted drawing/BOM items so `/api/tally` and `/api/export` can be
called without re-uploading anything.

NOTE: this is process-local memory, which is fine for the single-worker
deployment this project ships with (see `WORKERS` in config / Dockerfile).
For a horizontally-scaled deployment, swap this module's dict for Redis
(or any shared KV store) without changing the router code above it — the
public functions below are the only integration surface.
"""
from __future__ import annotations

import threading
import time
from typing import Any
from uuid import UUID

from app.core.exceptions import JobNotFoundError

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def create_job(job_id: UUID, filename: str, file_size: int, file_path: str) -> dict[str, Any]:
    with _lock:
        record = {
            "job_id": str(job_id),
            "status": "processing",
            "filename": filename,
            "file_size": file_size,
            "file_path": file_path,
            "created_at": time.time(),
            "drawing_items": [],
            "bom_items": [],
            "matched_pairs": [],
            "unmatched_drawing": [],
            "unmatched_bom": [],
            "pages_processed": 0,
            "error": None,
        }
        _jobs[str(job_id)] = record
        return record


def get_job(job_id: UUID | str) -> dict[str, Any]:
    with _lock:
        record = _jobs.get(str(job_id))
    if record is None:
        raise JobNotFoundError(f"No job found with id {job_id}.")
    return record


def update_job(job_id: UUID | str, **fields: Any) -> dict[str, Any]:
    with _lock:
        record = _jobs.get(str(job_id))
        if record is None:
            raise JobNotFoundError(f"No job found with id {job_id}.")
        record.update(fields)
        return record


def delete_job(job_id: UUID | str) -> None:
    with _lock:
        _jobs.pop(str(job_id), None)


def all_job_ids() -> list[str]:
    with _lock:
        return list(_jobs.keys())
