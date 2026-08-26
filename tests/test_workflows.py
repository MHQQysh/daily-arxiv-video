from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = [
    ROOT / ".github" / "workflows" / "deploy.yml",
    ROOT / ".github" / "workflows" / "process-curated.yml",
]


class WorkflowContractTests(unittest.TestCase):
    def test_both_workflows_run_the_complete_image_pipeline_in_order(self) -> None:
        required_fragments = [
            "actions/setup-node@v4",
            "npx playwright install --with-deps chromium",
            "python scripts/fetch_paper_images.py --max-items 0",
            "python scripts/build_paper_image_fallback_queue.py --max-items 0",
            "npm run paper-image:fallbacks",
            "python scripts/register_paper_image_fallbacks.py",
            "python scripts/fetch_pdf_fallback_images.py --max-items 0",
            "python scripts/build_site.py",
        ]

        for workflow in WORKFLOWS:
            with self.subTest(workflow=workflow.name):
                content = workflow.read_text(encoding="utf-8")
                positions = [content.index(fragment) for fragment in required_fragments]
                self.assertEqual(positions, sorted(positions))
                self.assertIn("contents: write", content)
                self.assertNotIn("fetch_paper_images.py --max-items 30", content)
                self.assertNotIn("build_paper_image_fallback_queue.py --max-items 20", content)

    def test_both_workflows_install_python_dependencies_before_image_steps(self) -> None:
        for workflow in WORKFLOWS:
            with self.subTest(workflow=workflow.name):
                content = workflow.read_text(encoding="utf-8")
                self.assertLess(
                    content.index("pip install -r requirements.txt"),
                    content.index("python scripts/fetch_paper_images.py"),
                )


if __name__ == "__main__":
    unittest.main()
