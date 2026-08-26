from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.prune_to_curated_video import load_curated_ids, prune_repository


HEADER = "| Date | Title | Link | Summary |\n|---|---|---|---|\n"


def paper_row(arxiv_id: str, title: str) -> str:
    return f"| 2026-08-25 | {title} | http://arxiv.org/abs/{arxiv_id} | summary |\n"


class PruneToCuratedVideoTests(unittest.TestCase):
    def make_repository(self) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        curated = root / "curation" / "video.txt"
        curated.parent.mkdir(parents=True)
        curated.write_text("# selected\n2608.00002\n2608.00003\n", encoding="utf-8")

        (root / "papers.md").write_text(
            HEADER
            + paper_row("2608.00001", "Old VLA paper")
            + paper_row("2608.00002", "Video paper A")
            + paper_row("2608.00003", "Video paper B"),
            encoding="utf-8",
        )

        image_dir = root / "site" / "assets" / "paper-images"
        image_dir.mkdir(parents=True)
        (image_dir / "old.png").write_bytes(b"old")
        (root / "site" / "assets" / "paper-images.json").write_text(
            json.dumps({"2608.00001": {"path": "assets/paper-images/old.png"}}),
            encoding="utf-8",
        )
        (root / "site" / "CNAME").write_text("example.test\n", encoding="utf-8")
        return temporary, root, curated

    def test_dry_run_reports_changes_without_writing(self) -> None:
        temporary, root, curated = self.make_repository()
        self.addCleanup(temporary.cleanup)

        before = (root / "papers.md").read_text(encoding="utf-8")
        report = prune_repository(root, curated, expected_count=2, apply=False)

        self.assertFalse(report.applied)
        self.assertEqual(report.original_papers, 3)
        self.assertEqual(report.kept_papers, 2)
        self.assertEqual(report.removed_papers, 1)
        self.assertEqual(report.removed_image_files, 1)
        self.assertEqual((root / "papers.md").read_text(encoding="utf-8"), before)
        self.assertTrue((root / "site" / "assets" / "paper-images" / "old.png").exists())

    def test_apply_keeps_only_curated_rows_and_resets_only_image_assets(self) -> None:
        temporary, root, curated = self.make_repository()
        self.addCleanup(temporary.cleanup)

        report = prune_repository(root, curated, expected_count=2, apply=True)
        result = (root / "papers.md").read_text(encoding="utf-8")

        self.assertTrue(report.applied)
        self.assertNotIn("2608.00001", result)
        self.assertLess(result.index("2608.00002"), result.index("2608.00003"))
        self.assertEqual(json.loads((root / "site" / "assets" / "paper-images.json").read_text(encoding="utf-8")), {})
        self.assertEqual(list((root / "site" / "assets" / "paper-images").iterdir()), [])
        self.assertEqual((root / "site" / "CNAME").read_text(encoding="utf-8"), "example.test\n")

    def test_missing_curated_id_fails_before_any_write(self) -> None:
        temporary, root, curated = self.make_repository()
        self.addCleanup(temporary.cleanup)
        curated.write_text("2608.00002\n2608.99999\n", encoding="utf-8")
        before = (root / "papers.md").read_text(encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "2608.99999"):
            prune_repository(root, curated, expected_count=2, apply=True)

        self.assertEqual((root / "papers.md").read_text(encoding="utf-8"), before)
        self.assertTrue((root / "site" / "assets" / "paper-images" / "old.png").exists())

    def test_duplicate_curated_id_is_rejected(self) -> None:
        temporary, _, curated = self.make_repository()
        self.addCleanup(temporary.cleanup)
        curated.write_text("2608.00002\n2608.00002\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "重复"):
            load_curated_ids(curated, expected_count=2)


if __name__ == "__main__":
    unittest.main()
