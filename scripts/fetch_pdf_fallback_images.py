#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""为仍缺少首图的论文从 arXiv PDF 生成可部署 PNG。

优先提取 PDF 前几页中面积最大的合格嵌入图片；若论文只有矢量图或没有
合格位图，则渲染第一页。该脚本是 HTML 下载和 Playwright 截图之后的最终兜底。
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import pymupdf as fitz

try:
    from scripts.fetch_paper_images import (
        IMAGE_DIR,
        INPUT_MD,
        MANIFEST_PATH,
        SITE_DIR,
        PaperRecord,
        http_get,
        load_manifest,
        manifest_entry_usable,
        normalize_abs_url,
        parse_markdown_table,
        read_text,
    )
except ModuleNotFoundError:
    from fetch_paper_images import (
        IMAGE_DIR,
        INPUT_MD,
        MANIFEST_PATH,
        SITE_DIR,
        PaperRecord,
        http_get,
        load_manifest,
        manifest_entry_usable,
        normalize_abs_url,
        parse_markdown_table,
        read_text,
    )


MIN_WIDTH = 320
MIN_HEIGHT = 160
MIN_AREA = 100_000
MIN_ASPECT_RATIO = 0.2
MAX_ASPECT_RATIO = 5.0


@dataclass(frozen=True)
class ExtractedImage:
    output_path: Path
    source: str
    width: int
    height: int


def pdf_url_for_id(arxiv_id: str) -> str:
    return f"https://arxiv.org/pdf/{arxiv_id}"


def is_eligible_image(width: int, height: int) -> bool:
    if width < MIN_WIDTH or height < MIN_HEIGHT or width * height < MIN_AREA:
        return False
    ratio = width / height
    return MIN_ASPECT_RATIO <= ratio <= MAX_ASPECT_RATIO


def _rgb_pixmap(document: fitz.Document, xref: int) -> fitz.Pixmap:
    pixmap = fitz.Pixmap(document, xref)
    if pixmap.colorspace is None:
        raise ValueError(f"PDF image xref {xref} has no color space")
    if pixmap.colorspace.n > 3:
        pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
    return pixmap


def extract_or_render_pdf_image(
    pdf_bytes: bytes,
    arxiv_id: str,
    image_dir: Path,
    *,
    pages_to_scan: int = 3,
    render_dpi: int = 144,
) -> ExtractedImage:
    image_dir.mkdir(parents=True, exist_ok=True)
    output_path = image_dir / f"{arxiv_id.replace('/', '-')}.png"

    with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
        if document.page_count < 1:
            raise ValueError("PDF has no pages")

        best: tuple[int, int, int, int] | None = None
        seen_xrefs: set[int] = set()
        for page_number in range(min(max(1, pages_to_scan), document.page_count)):
            page = document.load_page(page_number)
            for image_info in page.get_images(full=True):
                xref = int(image_info[0])
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
                try:
                    pixmap = _rgb_pixmap(document, xref)
                except (RuntimeError, ValueError):
                    continue
                width, height = pixmap.width, pixmap.height
                if not is_eligible_image(width, height):
                    continue
                area = width * height
                if best is None or area > best[0]:
                    best = (area, xref, width, height)

        if best is not None:
            _, xref, width, height = best
            pixmap = _rgb_pixmap(document, xref)
            output_path.write_bytes(pixmap.tobytes("png"))
            return ExtractedImage(output_path, "pdf:image", width, height)

        scale = max(render_dpi, 72) / 72
        pixmap = document.load_page(0).get_pixmap(
            matrix=fitz.Matrix(scale, scale),
            colorspace=fitz.csRGB,
            alpha=False,
        )
        output_path.write_bytes(pixmap.tobytes("png"))
        return ExtractedImage(output_path, "pdf:first-page", pixmap.width, pixmap.height)


def select_missing_records(
    records: List[PaperRecord],
    manifest: Dict[str, Dict[str, object]],
    max_items: int,
) -> List[PaperRecord]:
    missing = [
        record
        for record in records
        if not manifest_entry_usable(manifest.get(record.arxiv_id, {}))
    ]
    return missing[:max_items] if max_items > 0 else missing


def build_manifest_entry(
    record: PaperRecord,
    extracted: ExtractedImage,
    *,
    site_dir: Path,
    pdf_url: str,
) -> Dict[str, object]:
    relative_path = extracted.output_path.relative_to(site_dir).as_posix()
    return {
        "title": record.title,
        "abs_url": normalize_abs_url(record.link),
        "html_url": "",
        "path": relative_path,
        "image_url": pdf_url,
        "source": extracted.source,
        "score": 70 if extracted.source == "pdf:image" else 55,
        "content_type": "image/png",
        "inside_figure": extracted.source == "pdf:image",
        "width": extracted.width,
        "height": extracted.height,
    }


def save_manifest_atomic(manifest: Dict[str, Dict[str, object]], path: Path = MANIFEST_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch PDF fallback images for papers missing usable images.")
    parser.add_argument("--max-items", type=int, default=0, help="Process at most N missing papers. 0 means no limit.")
    parser.add_argument("--pages", type=int, default=3, help="Number of leading PDF pages to inspect for embedded images.")
    parser.add_argument("--render-dpi", type=int, default=144, help="DPI used when rendering the first-page fallback.")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    records = parse_markdown_table(read_text(INPUT_MD))
    manifest = load_manifest()
    targets = select_missing_records(records, manifest, args.max_items)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    print(f"论文总数: {len(records)}")
    print(f"待处理 PDF 兜底: {len(targets)}")
    updated = 0
    failed = 0

    for index, record in enumerate(targets, start=1):
        requested_url = pdf_url_for_id(record.arxiv_id)
        print(f"[{index}/{len(targets)}] {record.arxiv_id} -> {record.title}")
        try:
            pdf_bytes, _, final_url = http_get(requested_url, timeout=90)
            extracted = extract_or_render_pdf_image(
                pdf_bytes,
                record.arxiv_id,
                IMAGE_DIR,
                pages_to_scan=args.pages,
                render_dpi=args.render_dpi,
            )
            manifest[record.arxiv_id] = build_manifest_entry(
                record,
                extracted,
                site_dir=SITE_DIR,
                pdf_url=final_url or requested_url,
            )
            save_manifest_atomic(manifest)
            updated += 1
            print(f"  saved: {extracted.output_path}")
            print(f"  source: {extracted.source} ({extracted.width}x{extracted.height})")
        except Exception as exc:
            failed += 1
            print(f"  failed: {exc!r}")

    save_manifest_atomic(manifest)
    print("")
    print(f"完成: 新增/更新 {updated} 张, 失败 {failed} 张")
    print(f"Manifest: {MANIFEST_PATH}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
