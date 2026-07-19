"""Enumerations shared across schemas and services."""
from __future__ import annotations

from enum import Enum


class JobStatus(str, Enum):
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class TallyStatus(str, Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    MISSING_DRAWING = "missing-drawing"  # in BOM, not on drawing
    MISSING_BOM = "missing-bom"  # on drawing, not in BOM


class Severity(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExportFormat(str, Enum):
    CSV = "csv"
    JSON = "json"
    PDF = "pdf"
