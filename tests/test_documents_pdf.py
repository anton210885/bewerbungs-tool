"""Unit-Tests für PDF-Hilfen."""
from pathlib import Path

import pymupdf

from src.documents import pdf_to_images


def test_pdf_to_images_max_pages(tmp_path: Path):
    pdf_path = tmp_path / "demo.pdf"
    doc = pymupdf.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text((72, 72), f"Seite {i + 1}")
    doc.save(pdf_path)
    doc.close()

    all_pages = pdf_to_images(pdf_path, dpi=36)
    assert len(all_pages) == 3
    limited = pdf_to_images(pdf_path, dpi=36, max_pages=2)
    assert len(limited) == 2
    assert limited[0] == all_pages[0]
