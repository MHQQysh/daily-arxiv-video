from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz
from PIL import Image

from scripts.fetch_paper_images import PaperRecord
from scripts.fetch_pdf_fallback_images import (
    build_manifest_entry,
    extract_or_render_pdf_image,
    select_missing_records,
)


def make_pdf_with_embedded_image() -> bytes:
    image_buffer = io.BytesIO()
    Image.new("RGB", (800, 400), (25, 110, 210)).save(image_buffer, format="PNG")
    document = fitz.open()
    page = document.new_page(width=612, height=792)
    page.insert_image(fitz.Rect(40, 40, 572, 306), stream=image_buffer.getvalue())
    payload = document.tobytes()
    document.close()
    return payload


def make_vector_only_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 96), "Video paper without embedded raster figures")
    payload = document.tobytes()
    document.close()
    return payload


class FetchPdfFallbackImagesTests(unittest.TestCase):
    def test_extracts_largest_eligible_embedded_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image_dir = root / "site" / "assets" / "paper-images"
            result = extract_or_render_pdf_image(
                make_pdf_with_embedded_image(),
                "2608.00001",
                image_dir,
            )

            self.assertEqual(result.source, "pdf:image")
            self.assertEqual((result.width, result.height), (800, 400))
            with Image.open(result.output_path) as image:
                self.assertEqual(image.size, (800, 400))

            record = PaperRecord("Video paper", "https://arxiv.org/abs/2608.00001", "2608.00001")
            entry = build_manifest_entry(
                record,
                result,
                site_dir=root / "site",
                pdf_url="https://arxiv.org/pdf/2608.00001",
            )
            self.assertEqual(entry["path"], "assets/paper-images/2608.00001.png")
            self.assertEqual(entry["source"], "pdf:image")

    def test_renders_first_page_when_no_eligible_raster_image_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            image_dir = Path(temporary) / "images"
            result = extract_or_render_pdf_image(
                make_vector_only_pdf(),
                "2608.00002",
                image_dir,
                render_dpi=144,
            )

            self.assertEqual(result.source, "pdf:first-page")
            self.assertGreater(result.width, 1000)
            self.assertGreater(result.height, 1500)
            with Image.open(result.output_path) as image:
                self.assertEqual(image.size, (result.width, result.height))

    def test_existing_usable_manifest_entry_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site_dir = Path(temporary)
            image_path = site_dir / "assets" / "paper-images" / "2608.00001.png"
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"present")

            records = [PaperRecord("Video paper", "https://arxiv.org/abs/2608.00001", "2608.00001")]
            manifest = {
                "2608.00001": {
                    "path": "assets/paper-images/2608.00001.png",
                    "score": 70,
                    "image_url": "https://arxiv.org/html/2608.00001v1/figure.png",
                }
            }

            with patch("scripts.fetch_paper_images.SITE_DIR", site_dir):
                # manifest_entry_usable resolves SITE_DIR in its defining module.
                self.assertEqual(select_missing_records(records, manifest, 0), [])


if __name__ == "__main__":
    unittest.main()
