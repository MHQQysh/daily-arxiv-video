from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, time, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests

from scripts.arxiv_crawler import ArxivCollector, _TimeoutSession
from scripts.video_topics import FALLBACK_QUERY, PRIMARY_QUERY


HEADER = "| 日期 | 标题 | 链接 | 简要总结 |\n| --- | --- | --- | --- |\n"


def make_result(
    number: int,
    published_date: date,
    *,
    title: str | None = None,
    summary: str = "video generation video diffusion video",
    category: str = "cs.CV",
) -> SimpleNamespace:
    timestamp = datetime.combine(published_date, time(12), tzinfo=timezone.utc)
    return SimpleNamespace(
        entry_id=f"https://arxiv.org/abs/2608.{number:05d}v1",
        title=title or f"Video Paper {number}",
        summary=summary,
        primary_category=category,
        published=timestamp,
        updated=timestamp,
    )


class StubCollector(ArxivCollector):
    def __init__(self, papers_path: str, responses: dict[str, list[SimpleNamespace]]) -> None:
        super().__init__(
            papers_path,
            daily_results=10,
            primary_results=30,
            fallback_results=70,
        )
        self.responses = responses
        self.calls: list[tuple[str, int]] = []
        self.raw_queries: list[str] = []

    def _search(self, query: str, max_results: int) -> list[SimpleNamespace]:
        self.raw_queries.append(query)
        base_query = FALLBACK_QUERY if FALLBACK_QUERY in query else PRIMARY_QUERY
        self.calls.append((base_query, max_results))
        return list(self.responses.get(base_query, []))


class ArxivCrawlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.papers_path = Path(self.temporary.name) / "papers.md"
        self.papers_path.write_text(HEADER, encoding="utf-8")

    def write_rows(self, published_date: date, numbers: range) -> None:
        rows = "".join(
            f"| {published_date.isoformat()} | Existing {number} | "
            f"https://arxiv.org/abs/2608.{number:05d} | summary |\n"
            for number in numbers
        )
        self.papers_path.write_text(HEADER + rows, encoding="utf-8")

    def count_date(self, published_date: date) -> int:
        return sum(
            line.split("|")[1].strip() == published_date.isoformat()
            for line in self.papers_path.read_text(encoding="utf-8").splitlines()[2:]
            if "arxiv.org/abs/" in line
        )

    def test_target_date_with_three_existing_rows_adds_only_seven(self) -> None:
        target = date(2026, 8, 25)
        self.write_rows(target, range(1, 4))
        primary = [make_result(number, target) for number in range(4, 6)]
        fallback = [make_result(number, target) for number in range(4, 13)]
        collector = StubCollector(
            str(self.papers_path),
            {PRIMARY_QUERY: primary, FALLBACK_QUERY: fallback},
        )

        self.assertEqual(collector.run_daily(target_date=target), 7)
        self.assertEqual(self.count_date(target), 10)
        self.assertEqual(
            collector.calls,
            [(PRIMARY_QUERY, 30), (FALLBACK_QUERY, 70)],
        )

    def test_target_date_with_ten_existing_rows_makes_no_request(self) -> None:
        target = date(2026, 8, 25)
        self.write_rows(target, range(1, 11))
        collector = StubCollector(str(self.papers_path), {})

        self.assertEqual(collector.run_daily(target_date=target), 0)
        self.assertEqual(collector.calls, [])

    def test_explicit_target_date_is_sent_to_arxiv_query(self) -> None:
        target = date(2026, 8, 25)
        collector = StubCollector(str(self.papers_path), {PRIMARY_QUERY: [], FALLBACK_QUERY: []})

        collector.run_daily(target_date=target, dry_run=True)

        self.assertTrue(collector.raw_queries)
        self.assertTrue(
            all("submittedDate:[202608250000 TO 202608252359]" in query for query in collector.raw_queries)
        )

    def test_fallback_query_runs_only_when_primary_cannot_fill_target(self) -> None:
        target = date(2026, 8, 25)
        self.write_rows(target, range(1, 8))
        primary = [make_result(number, target) for number in range(8, 11)]
        collector = StubCollector(str(self.papers_path), {PRIMARY_QUERY: primary})

        self.assertEqual(collector.run_daily(target_date=target), 3)
        self.assertEqual(collector.calls, [(PRIMARY_QUERY, 30)])

    def test_unrelated_fallback_candidate_is_rejected(self) -> None:
        target = date(2026, 8, 25)
        self.write_rows(target, range(1, 4))
        unrelated = make_result(
            20,
            target,
            title="Image Classification",
            summary="A demo video is available.",
        )
        collector = StubCollector(
            str(self.papers_path),
            {PRIMARY_QUERY: [], FALLBACK_QUERY: [unrelated]},
        )

        self.assertEqual(collector.run_daily(target_date=target), 0)
        self.assertEqual(self.count_date(target), 3)

    def test_other_dates_duplicates_and_disallowed_categories_are_ignored(self) -> None:
        target = date(2026, 8, 25)
        self.write_rows(target, range(1, 4))
        duplicate = make_result(1, target)
        other_date = make_result(20, date(2026, 8, 24))
        disallowed = make_result(21, target, category="physics.gen-ph")
        qualified = make_result(22, target)
        collector = StubCollector(
            str(self.papers_path),
            {
                PRIMARY_QUERY: [],
                FALLBACK_QUERY: [duplicate, other_date, disallowed, qualified],
            },
        )

        self.assertEqual(collector.run_daily(target_date=target), 1)
        self.assertEqual(self.count_date(target), 4)

    def test_dry_run_returns_count_without_modifying_markdown(self) -> None:
        target = date(2026, 8, 25)
        self.write_rows(target, range(1, 4))
        before = self.papers_path.read_text(encoding="utf-8")
        primary = [make_result(number, target) for number in range(4, 11)]
        collector = StubCollector(str(self.papers_path), {PRIMARY_QUERY: primary})

        self.assertEqual(collector.run_daily(target_date=target, dry_run=True), 7)
        self.assertEqual(self.papers_path.read_text(encoding="utf-8"), before)

    def test_automatic_mode_uses_newest_primary_release_date(self) -> None:
        older = date(2026, 8, 24)
        newest = date(2026, 8, 25)
        primary = [make_result(30, older), make_result(31, newest)]
        fallback = [make_result(number, newest) for number in range(32, 41)]
        collector = StubCollector(
            str(self.papers_path),
            {PRIMARY_QUERY: primary, FALLBACK_QUERY: fallback},
        )

        self.assertEqual(collector.run_daily(), 10)
        self.assertEqual(self.count_date(newest), 10)
        self.assertEqual(self.count_date(older), 0)

    def test_request_session_applies_ten_second_timeout(self) -> None:
        session = _TimeoutSession(10)
        with patch.object(requests.Session, "request", return_value=object()) as request:
            session.request("GET", "https://export.arxiv.org/api/query")

        self.assertEqual(request.call_args.kwargs["timeout"], 10)


if __name__ == "__main__":
    unittest.main()
