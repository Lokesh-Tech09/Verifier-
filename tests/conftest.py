from __future__ import annotations

import fitz
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _make_pdf_bytes(left_lines: list[str], right_lines: list[str]) -> bytes:
    """Build a minimal single-page PDF with text on the left half (drawing
    callouts) and text on the right half (a pseudo BOM), for smoke tests."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)  # Letter

    y = 100
    for line in left_lines:
        page.insert_text((50, y), line, fontsize=11)
        y += 20

    y = 100
    for line in right_lines:
        page.insert_text((340, y), line, fontsize=11)
        y += 20

    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture()
def sample_pdf_bytes() -> bytes:
    left = ["4 - Bolt M8x20", "2 - Bracket Assembly"]
    right = ["QTY  DESCRIPTION", "4    Bolt M8x20", "2    Bracket Assembly"]
    return _make_pdf_bytes(left, right)


@pytest.fixture()
def not_a_pdf_bytes() -> bytes:
    return b"this is definitely not a pdf file"
