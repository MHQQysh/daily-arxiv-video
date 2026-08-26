#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""将仓库精确收敛到审核过的 Video 论文清单。

默认只报告将发生的变化；只有显式传入 ``--apply`` 才会写入文件。
图片清理范围被硬编码并校验为 ``site/assets/paper-images``，避免误删。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARXIV_ID_RE = re.compile(r"arxiv\.org/(?:abs|pdf|html)/([^\s|?#]+)", re.IGNORECASE)


@dataclass(frozen=True)
class PaperRow:
    arxiv_id: str
    line_index: int
    text: str


@dataclass(frozen=True)
class CleanupReport:
    applied: bool
    original_papers: int
    kept_papers: int
    removed_papers: int
    removed_image_files: int
    papers_path: str
    image_dir: str
    manifest_path: str


def normalize_arxiv_id(value: str) -> str:
    arxiv_id = value.strip().rstrip("/")
    if arxiv_id.lower().endswith(".pdf"):
        arxiv_id = arxiv_id[:-4]
    return re.sub(r"v\d+$", "", arxiv_id, flags=re.IGNORECASE)


def load_curated_ids(path: Path, expected_count: int | None = 60) -> list[str]:
    if not path.is_file():
        raise FileNotFoundError(f"策展清单不存在: {path}")

    curated_ids: list[str] = []
    seen: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        value = raw_line.strip()
        if not value or value.startswith("#"):
            continue
        arxiv_id = normalize_arxiv_id(value)
        if not re.fullmatch(r"\d{4}\.\d{4,5}", arxiv_id):
            raise ValueError(f"无效 arXiv ID: {value}")
        if arxiv_id in seen:
            raise ValueError(f"策展清单包含重复 ID: {arxiv_id}")
        seen.add(arxiv_id)
        curated_ids.append(arxiv_id)

    if expected_count is not None and len(curated_ids) != expected_count:
        raise ValueError(f"策展清单应包含 {expected_count} 篇，实际为 {len(curated_ids)} 篇")
    return curated_ids


def parse_paper_rows(markdown: str) -> tuple[list[str], list[PaperRow]]:
    lines = markdown.splitlines(keepends=True)
    rows: list[PaperRow] = []
    seen: set[str] = set()

    for line_index, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            continue
        match = ARXIV_ID_RE.search(line)
        if not match:
            continue
        arxiv_id = normalize_arxiv_id(match.group(1))
        if arxiv_id in seen:
            raise ValueError(f"papers.md 包含重复 ID: {arxiv_id}")
        seen.add(arxiv_id)
        rows.append(PaperRow(arxiv_id=arxiv_id, line_index=line_index, text=line))

    return lines, rows


def build_pruned_markdown(markdown: str, keep_ids: list[str]) -> str:
    lines, rows = parse_paper_rows(markdown)
    available = {row.arxiv_id for row in rows}
    missing = [arxiv_id for arxiv_id in keep_ids if arxiv_id not in available]
    if missing:
        raise ValueError(f"策展论文未出现在 papers.md: {', '.join(missing)}")

    keep = set(keep_ids)
    row_by_index = {row.line_index: row for row in rows}
    return "".join(
        line
        for line_index, line in enumerate(lines)
        if line_index not in row_by_index or row_by_index[line_index].arxiv_id in keep
    )


def _assert_exact_image_target(root: Path, image_dir: Path) -> None:
    resolved_root = root.resolve()
    resolved_target = image_dir.resolve()
    expected = (resolved_root / "site" / "assets" / "paper-images").resolve()
    if resolved_target != expected or not resolved_target.is_relative_to(resolved_root):
        raise ValueError(f"拒绝清理非预期图片目录: {resolved_target}")


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def prune_repository(
    root: Path,
    curated_file: Path,
    *,
    expected_count: int = 60,
    apply: bool = False,
) -> CleanupReport:
    root = root.resolve()
    papers_path = root / "papers.md"
    image_dir = root / "site" / "assets" / "paper-images"
    manifest_path = root / "site" / "assets" / "paper-images.json"
    _assert_exact_image_target(root, image_dir)

    curated_ids = load_curated_ids(curated_file.resolve(), expected_count=expected_count)
    markdown = papers_path.read_text(encoding="utf-8")
    _, rows = parse_paper_rows(markdown)
    pruned_markdown = build_pruned_markdown(markdown, curated_ids)
    image_file_count = sum(1 for path in image_dir.rglob("*") if path.is_file()) if image_dir.exists() else 0

    report = CleanupReport(
        applied=apply,
        original_papers=len(rows),
        kept_papers=len(curated_ids),
        removed_papers=len(rows) - len(curated_ids),
        removed_image_files=image_file_count,
        papers_path=str(papers_path),
        image_dir=str(image_dir),
        manifest_path=str(manifest_path),
    )

    if not apply:
        return report

    _atomic_write_text(papers_path, pruned_markdown)
    if image_dir.exists():
        shutil.rmtree(image_dir)
    image_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(manifest_path, "{}\n")
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prune the repository to the curated Video paper list.")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT, help="Repository root.")
    parser.add_argument("--curated-file", type=Path, required=True, help="Text file containing one arXiv ID per line.")
    parser.add_argument("--expected-count", type=int, default=60, help="Required number of curated papers.")
    parser.add_argument("--apply", action="store_true", help="Apply the validated cleanup. Default is dry-run.")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    root = args.root.resolve()
    curated_file = args.curated_file
    if not curated_file.is_absolute():
        curated_file = root / curated_file

    report = prune_repository(
        root,
        curated_file,
        expected_count=args.expected_count,
        apply=args.apply,
    )
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    print("已执行清理。" if report.applied else "Dry-run：未修改任何文件；确认后使用 --apply。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
