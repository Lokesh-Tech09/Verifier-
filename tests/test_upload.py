from __future__ import annotations

from app.core.config import settings


def test_upload_valid_pdf_returns_job_id(client, sample_pdf_bytes):
    resp = client.post(
        "/api/upload",
        files={"pdf": ("drawing.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["status"] == "processing"
    assert body["data"]["filename"] == "drawing.pdf"
    assert "job_id" in body["data"]


def test_upload_rejects_non_pdf(client, not_a_pdf_bytes):
    resp = client.post(
        "/api/upload",
        files={"pdf": ("notes.txt", not_a_pdf_bytes, "text/plain")},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "UPLOAD_INVALID"


def test_upload_rejects_oversized_file(client, sample_pdf_bytes, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_MAX_SIZE", 10)  # absurdly small, for the test
    resp = client.post(
        "/api/upload",
        files={"pdf": ("drawing.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "UPLOAD_TOO_LARGE"


def test_upload_sanitizes_path_traversal_filename(client, sample_pdf_bytes):
    resp = client.post(
        "/api/upload",
        files={"pdf": ("../../etc/passwd.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 200
    filename = resp.json()["data"]["filename"]
    assert "/" not in filename and ".." not in filename
