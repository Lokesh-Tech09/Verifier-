from __future__ import annotations

import uuid


def test_analyze_unknown_job_returns_404(client):
    fake_job_id = uuid.uuid4()
    resp = client.post(f"/api/analyze/{fake_job_id}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_status_unknown_job_returns_404(client):
    fake_job_id = uuid.uuid4()
    resp = client.get(f"/api/status/{fake_job_id}")
    assert resp.status_code == 404


def test_analyze_smoke_after_upload(client, sample_pdf_bytes):
    """End-to-end smoke test: upload then analyze. Since OCR accuracy on a
    synthetic, tiny test PDF can vary by environment, we only assert the
    pipeline runs and returns a well-formed response — not exact item
    counts."""
    upload_resp = client.post(
        "/api/upload",
        files={"pdf": ("drawing.pdf", sample_pdf_bytes, "application/pdf")},
    )
    job_id = upload_resp.json()["data"]["job_id"]

    analyze_resp = client.post(f"/api/analyze/{job_id}")
    assert analyze_resp.status_code == 200
    body = analyze_resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["job_id"] == job_id
    assert data["pages_processed"] == 1
    assert "drawing_items" in data
    assert "bom_items" in data
    assert "matched_pairs" in data
