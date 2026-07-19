"""Pydantic v2 schemas for requests, responses, and internal data shapes."""
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.models.enums import ExportFormat, JobStatus, Severity, TallyStatus


# ──────────────────────────────────────────────────────────────────────────
# Generic envelope
# ──────────────────────────────────────────────────────────────────────────
class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class APIResponse(BaseModel):
    success: bool
    data: dict[str, Any] | None = None
    message: str | None = None
    error: ErrorDetail | None = None


# ──────────────────────────────────────────────────────────────────────────
# Upload
# ──────────────────────────────────────────────────────────────────────────
class UploadResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    filename: str
    file_size: int
    message: str


# ──────────────────────────────────────────────────────────────────────────
# Extraction (drawing + BOM items)
# ──────────────────────────────────────────────────────────────────────────
class BBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class DrawingItem(BaseModel):
    id: str = Field(default_factory=lambda: f"draw-{uuid4().hex[:8]}")
    description: str
    quantity: float
    unit: str = "ea"
    raw_text: str = ""
    confidence: float = Field(default=1.0, ge=0, le=1)
    page: int = 1
    bbox: BBox | None = None


class BOMItem(BaseModel):
    id: str = Field(default_factory=lambda: f"bom-{uuid4().hex[:8]}")
    description: str
    quantity: float
    unit: str = "ea"
    piece_mark: str | None = None
    material: str | None = None
    row_index: int = 0
    raw_text: str = ""


class MatchedPair(BaseModel):
    drawing_item: DrawingItem
    bom_item: BOMItem
    match_score: float = Field(ge=0, le=100)


class AnalyzeResponseData(BaseModel):
    job_id: UUID
    status: JobStatus
    pages_processed: int
    drawing_items: list[DrawingItem]
    bom_items: list[BOMItem]
    matched_pairs: list[MatchedPair]
    unmatched_drawing: list[DrawingItem]
    unmatched_bom: list[BOMItem]


# ──────────────────────────────────────────────────────────────────────────
# Tally
# ──────────────────────────────────────────────────────────────────────────
class TallyRequest(BaseModel):
    job_id: UUID | None = None
    drawing_items: list[DrawingItem] = Field(default_factory=list)
    bom_items: list[BOMItem] = Field(default_factory=list)


class TallyResult(BaseModel):
    description: str
    drawing_qty: float | None
    bom_qty: float | None
    difference: float
    status: TallyStatus
    draw_unit: str = "ea"
    bom_unit: str = "ea"
    action_required: str | None
    severity: Severity


class TallyResponseData(BaseModel):
    job_id: UUID | None
    total_items: int
    matched: int
    mismatched: int
    missing: int
    results: list[TallyResult]


# ──────────────────────────────────────────────────────────────────────────
# Export
# ──────────────────────────────────────────────────────────────────────────
class ExportRequest(BaseModel):
    format: ExportFormat
    job_id: UUID | None = None
    filename: str | None = None
    results: list[TallyResult]
