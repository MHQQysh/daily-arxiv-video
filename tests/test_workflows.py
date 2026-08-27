from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = [
    ROOT / ".github" / "workflows" / "deploy.yml",
    ROOT / ".github" / "workflows" / "process-curated.yml",
]


class WorkflowContractTests(unittest.TestCase):
    def test_updater_is_schedule_or_manual_only_and_avoids_top_of_hour(self) -> None:
        content = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", content)
        self.assertIn("schedule:", content)
        self.assertIn("cron: '17 4 * * *'", content)
        self.assertIn("cron: '34 14 * * *'", content)
        self.assertEqual(content.count("cron:"), 2)
        self.assertNotIn("\n  push:", content)
        self.assertIn('group: "daily-video-pages"', content)
        self.assertIn("cancel-in-progress: true", content)

    def test_summary_api_cannot_block_paper_and_image_updates(self) -> None:
        content = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
        summary_block = content[content.index("- name: 生成论文摘要") : content.index("- name: 抓取论文首图")]
        self.assertIn("timeout-minutes: 4", summary_block)
        self.assertIn("continue-on-error: true", summary_block)
        self.assertIn("MODELSCOPE_TIMEOUT: 30", summary_block)
        self.assertIn("HTTP_TIMEOUT: 15", summary_block)
        self.assertIn("HTTP_MAX_RETRIES: 1", summary_block)
        self.assertIn("API_MAX_RETRIES: 1", summary_block)
        self.assertIn("BATCH_WRITE_SIZE: 1", summary_block)

    def test_deploy_workflow_bounds_daily_ten_paper_search(self) -> None:
        content = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
        for fragment in (
            "add_new_papers:",
            "target_date:",
            "timeout-minutes: 3",
            "ARXIV_DAILY_RESULTS: 10",
            "ARXIV_PRIMARY_RESULTS: 30",
            "ARXIV_FALLBACK_RESULTS: 70",
            "ARXIV_PAGE_SIZE: 70",
            "ARXIV_REQUEST_TIMEOUT_SECONDS: 10",
            "ARXIV_RETRY_BASE_SECONDS: 5",
            "ARXIV_MAX_RETRIES: 2",
            "python -u scripts/arxiv_crawler.py --dry-run",
            "python -m unittest discover -s tests -v",
        ):
            self.assertIn(fragment, content)
        self.assertIn('github.event_name }}" = "schedule"', content)
        self.assertNotIn("ARXIV_DAILY_RESULTS: 5", content)
        self.assertNotIn("ARXIV_DELAY_SECONDS: 15", content)
        self.assertNotIn("ARXIV_RETRY_BASE_SECONDS: 60", content)

    def test_playwright_fallback_resolves_module_path_cross_platform(self) -> None:
        content = (ROOT / "scripts" / "render_paper_image_fallbacks.mjs").read_text(encoding="utf-8")
        self.assertIn("fileURLToPath(import.meta.url)", content)
        self.assertNotIn("new URL(import.meta.url).pathname", content)

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

    def test_publish_only_workflow_never_crawls_or_rewrites_papers(self) -> None:
        content = (ROOT / ".github" / "workflows" / "publish-site.yml").read_text(encoding="utf-8")
        self.assertIn("\n  push:", content)
        self.assertIn("branches: [ master, main ]", content)
        self.assertIn('group: "daily-video-pages"', content)
        self.assertIn("cancel-in-progress: true", content)
        self.assertIn("actions/upload-pages-artifact@v4", content)
        self.assertIn("actions/deploy-pages@v4", content)
        self.assertIn("contents: read", content)
        self.assertNotIn("arxiv_crawler.py", content)
        self.assertNotIn("generate_summaries.py", content)
        self.assertNotIn("fetch_paper_images.py", content)
        self.assertNotIn("git push", content)


if __name__ == "__main__":
    unittest.main()
