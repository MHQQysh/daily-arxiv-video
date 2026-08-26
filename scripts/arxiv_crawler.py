from __future__ import annotations

import argparse
import os
import re
import time
from collections import Counter
from datetime import date, datetime
from typing import List, Optional, Set, Tuple

import arxiv
import requests

try:
    from scripts.video_topics import (
        ALLOWED_PRIMARY_CATEGORIES,
        FALLBACK_QUERY,
        PRIMARY_QUERY,
        is_relevant_video_paper,
        relevance_score,
    )
except ModuleNotFoundError:
    from video_topics import (
        ALLOWED_PRIMARY_CATEGORIES,
        FALLBACK_QUERY,
        PRIMARY_QUERY,
        is_relevant_video_paper,
        relevance_score,
    )


_ARXIV_ID_PATTERN = r"(?:\d{4}\.\d{4,5}|[a-z][a-z0-9.-]*/\d{7})(?:v\d+)?"
_ARXIV_VALUE_PATTERN = re.compile(
    r"^\s*(?:(?:https?://(?:(?:www|export)\.)?arxiv\.org/(?:abs|pdf)/)|arxiv:)?"
    r"(?P<identifier>" + _ARXIV_ID_PATTERN + r")(?:\.pdf)?/?(?:[?#].*)?\s*$",
    re.IGNORECASE,
)
_ARXIV_ABS_LINK_PATTERN = re.compile(
    r"https?://(?:(?:www|export)\.)?arxiv\.org/abs/" + _ARXIV_ID_PATTERN,
    re.IGNORECASE,
)
_DAILY_TARGET_HARD_MAX = 20
_PRIMARY_RESULTS_HARD_MAX = 100
_FALLBACK_RESULTS_HARD_MAX = 200


class _TimeoutSession(requests.Session):
    """为 arxiv.py 没有显式 timeout 的请求补上硬超时。"""

    def __init__(self, timeout_seconds: float):
        super().__init__()
        self.timeout_seconds = timeout_seconds

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", self.timeout_seconds)
        return super().request(method, url, **kwargs)


class ArxivCollector:
    """按 arXiv 发布日期维护每日最多 10 篇高相关 Video 论文。"""

    _ALLOWED_PRIMARY_CATEGORIES = ALLOWED_PRIMARY_CATEGORIES

    def __init__(
        self,
        papers_path: str,
        init_results: Optional[int] = None,
        daily_results: Optional[int] = None,
        query_keyword: Optional[str] = None,
        primary_results: Optional[int] = None,
        fallback_results: Optional[int] = None,
    ) -> None:
        self.papers_path = papers_path
        self.daily_results = self._require_positive_int(
            "daily_results",
            daily_results if daily_results is not None else int(os.getenv("ARXIV_DAILY_RESULTS", "10")),
            maximum=_DAILY_TARGET_HARD_MAX,
        )
        self.primary_results = self._require_positive_int(
            "primary_results",
            primary_results if primary_results is not None else int(os.getenv("ARXIV_PRIMARY_RESULTS", "30")),
            maximum=_PRIMARY_RESULTS_HARD_MAX,
        )
        self.fallback_results = self._require_positive_int(
            "fallback_results",
            fallback_results if fallback_results is not None else int(os.getenv("ARXIV_FALLBACK_RESULTS", "70")),
            maximum=_FALLBACK_RESULTS_HARD_MAX,
        )
        self.init_results = init_results if init_results is not None else self.primary_results
        self.primary_query = query_keyword or os.getenv("ARXIV_QUERY_KEYWORD") or PRIMARY_QUERY
        self.fallback_query = os.getenv("ARXIV_FALLBACK_QUERY") or FALLBACK_QUERY
        self.arxiv_page_size = self._require_positive_int(
            "ARXIV_PAGE_SIZE",
            int(os.getenv("ARXIV_PAGE_SIZE", str(max(self.primary_results, self.fallback_results)))),
            maximum=2000,
        )
        self.arxiv_delay_seconds = self._require_positive_float(
            "ARXIV_DELAY_SECONDS",
            float(os.getenv("ARXIV_DELAY_SECONDS", "3")),
        )
        self.arxiv_request_timeout_seconds = self._require_positive_float(
            "ARXIV_REQUEST_TIMEOUT_SECONDS",
            float(os.getenv("ARXIV_REQUEST_TIMEOUT_SECONDS", "10")),
        )
        self.arxiv_max_retries = self._require_positive_int(
            "ARXIV_MAX_RETRIES",
            int(os.getenv("ARXIV_MAX_RETRIES", "2")),
        )
        self._client = arxiv.Client(
            page_size=self.arxiv_page_size,
            delay_seconds=self.arxiv_delay_seconds,
            num_retries=0,
        )
        self._client._session = _TimeoutSession(self.arxiv_request_timeout_seconds)

    @staticmethod
    def _require_positive_int(name: str, value: int, maximum: Optional[int] = None) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{name} 必须是正整数")
        if maximum is not None and value > maximum:
            raise ValueError(f"{name} 不能大于 {maximum}")
        return value

    @staticmethod
    def _require_positive_float(name: str, value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"{name} 必须是正数")
        return float(value)

    def _search(self, query: str, max_results: int) -> List[arxiv.Result]:
        retry_base_seconds = self._require_positive_float(
            "ARXIV_RETRY_BASE_SECONDS",
            float(os.getenv("ARXIV_RETRY_BASE_SECONDS", "5")),
        )
        last_error: Optional[Exception] = None
        for attempt in range(self.arxiv_max_retries):
            try:
                print(
                    f"arXiv 查询 {query!r}，尝试 {attempt + 1}/{self.arxiv_max_retries}，候选上限 {max_results}",
                    flush=True,
                )
                search = arxiv.Search(
                    query=query,
                    max_results=max_results,
                    sort_by=arxiv.SortCriterion.SubmittedDate,
                    sort_order=arxiv.SortOrder.Descending,
                )
                results = list(self._client.results(search))
                print(f"arXiv 返回 {len(results)} 条候选", flush=True)
                return results
            except Exception as exc:
                last_error = exc
                if attempt < self.arxiv_max_retries - 1:
                    wait_seconds = retry_base_seconds * (2**attempt)
                    print(f"arXiv 查询失败，{wait_seconds:.0f} 秒后重试: {exc!r}", flush=True)
                    time.sleep(wait_seconds)
        raise RuntimeError(f"arXiv 查询达到最大重试次数: {last_error!r}")

    @staticmethod
    def _canonical_arxiv_id(value: str) -> Optional[str]:
        match = _ARXIV_VALUE_PATTERN.fullmatch(value or "")
        if match is None:
            return None
        return re.sub(r"v\d+$", "", match.group("identifier"), flags=re.IGNORECASE).lower()

    def _normalize_link(self, value: str) -> str:
        canonical_id = self._canonical_arxiv_id(value)
        return f"https://arxiv.org/abs/{canonical_id}" if canonical_id else value.strip()

    @staticmethod
    def _query_for_date(query: str, target_date: Optional[date]) -> str:
        if target_date is None:
            return query
        day = target_date.strftime("%Y%m%d")
        return f"({query}) AND submittedDate:[{day}0000 TO {day}2359]"

    @staticmethod
    def _result_date(result: arxiv.Result) -> Optional[date]:
        published = getattr(result, "published", None)
        if isinstance(published, datetime):
            return published.date()
        if isinstance(published, date):
            return published
        return None

    def _ensure_md_header(self) -> None:
        if os.path.exists(self.papers_path):
            return
        with open(self.papers_path, "w", encoding="utf-8") as file:
            file.write("| 日期 | 标题 | 链接 | 简要总结 |\n")
            file.write("| --- | --- | --- | --- |\n")

    def _load_existing_state(self) -> Tuple[Set[str], Counter[str]]:
        identifiers: Set[str] = set()
        date_counts: Counter[str] = Counter()
        if not os.path.exists(self.papers_path):
            return identifiers, date_counts
        with open(self.papers_path, "r", encoding="utf-8") as file:
            for line in file:
                match = _ARXIV_ABS_LINK_PATTERN.search(line)
                parts = line.split("|")
                if match is None or len(parts) < 4:
                    continue
                canonical_id = self._canonical_arxiv_id(match.group(0))
                if canonical_id is None:
                    continue
                identifiers.add(canonical_id)
                date_counts[parts[1].strip()] += 1
        return identifiers, date_counts

    def _format_row(self, result: arxiv.Result) -> str:
        published_date = self._result_date(result)
        date_text = published_date.isoformat() if published_date else ""
        title = (getattr(result, "title", "") or "").replace("|", "\\|").strip()
        link = self._normalize_link(getattr(result, "entry_id", "") or "")
        return (
            f"| {date_text} | {title} | {link} | "
            "<details><summary>展开</summary>待生成</details> |\n"
        )

    def _append_rows(self, rows: List[str]) -> None:
        if not rows:
            return
        self._ensure_md_header()
        with open(self.papers_path, "r", encoding="utf-8") as file:
            lines = file.readlines()
        insert_index = 2 if len(lines) >= 2 else len(lines)
        with open(self.papers_path, "w", encoding="utf-8") as file:
            file.writelines(lines[:insert_index] + rows + lines[insert_index:])

    def _newest_candidate_date(self, results: List[arxiv.Result], *, require_relevance: bool) -> Optional[date]:
        dates: List[date] = []
        for result in results:
            if getattr(result, "primary_category", "") not in self._ALLOWED_PRIMARY_CATEGORIES:
                continue
            if require_relevance and not is_relevant_video_paper(
                getattr(result, "title", "") or "",
                getattr(result, "summary", "") or "",
            ):
                continue
            result_date = self._result_date(result)
            if result_date is not None:
                dates.append(result_date)
        return max(dates) if dates else None

    def _qualified_for_date(
        self,
        results: List[arxiv.Result],
        target_date: date,
        existing: Set[str],
        *,
        require_relevance: bool,
    ) -> List[arxiv.Result]:
        qualified: List[arxiv.Result] = []
        seen = set(existing)
        for result in results:
            if getattr(result, "primary_category", "") not in self._ALLOWED_PRIMARY_CATEGORIES:
                continue
            if self._result_date(result) != target_date:
                continue
            if require_relevance and not is_relevant_video_paper(
                getattr(result, "title", "") or "",
                getattr(result, "summary", "") or "",
            ):
                continue
            canonical_id = self._canonical_arxiv_id(getattr(result, "entry_id", "") or "")
            if canonical_id is None or canonical_id in seen:
                continue
            seen.add(canonical_id)
            qualified.append(result)
        if require_relevance:
            qualified.sort(
                key=lambda result: (
                    relevance_score(
                        getattr(result, "title", "") or "",
                        getattr(result, "summary", "") or "",
                    ),
                    str(getattr(result, "published", "")),
                    self._canonical_arxiv_id(getattr(result, "entry_id", "") or "") or "",
                ),
                reverse=True,
            )
        return qualified

    def run_daily(self, target_date: Optional[date] = None, dry_run: bool = False) -> int:
        existing, date_counts = self._load_existing_state()
        if target_date is not None and date_counts[target_date.isoformat()] >= self.daily_results:
            print(f"{target_date.isoformat()} 已有 {date_counts[target_date.isoformat()]} 篇，无需补足", flush=True)
            return 0

        primary_results: List[arxiv.Result] = []
        primary_error: Optional[Exception] = None
        try:
            primary_results = self._search(
                self._query_for_date(self.primary_query, target_date),
                self.primary_results,
            )
        except Exception as exc:
            primary_error = exc
            print(f"高精度查询失败，尝试扩展查询: {exc!r}", flush=True)

        resolved_date = target_date or self._newest_candidate_date(primary_results, require_relevance=False)
        primary_candidates: List[arxiv.Result] = []
        if resolved_date is not None:
            primary_candidates = self._qualified_for_date(
                primary_results,
                resolved_date,
                existing,
                require_relevance=False,
            )

        existing_count = date_counts[resolved_date.isoformat()] if resolved_date else 0
        needed = max(0, self.daily_results - existing_count)
        selected = primary_candidates[:needed]

        if resolved_date is None or len(selected) < needed:
            try:
                fallback_results = self._search(
                    self._query_for_date(self.fallback_query, target_date),
                    self.fallback_results,
                )
            except Exception as exc:
                if primary_error is not None:
                    raise RuntimeError(
                        f"高精度和扩展查询均失败: primary={primary_error!r}; fallback={exc!r}"
                    ) from exc
                raise RuntimeError(f"扩展查询失败，无法完成每日补足: {exc!r}") from exc

            if resolved_date is None:
                resolved_date = self._newest_candidate_date(fallback_results, require_relevance=True)
                existing_count = date_counts[resolved_date.isoformat()] if resolved_date else 0
                needed = max(0, self.daily_results - existing_count)
                if resolved_date is not None:
                    primary_candidates = self._qualified_for_date(
                        primary_results,
                        resolved_date,
                        existing,
                        require_relevance=False,
                    )
                    selected = primary_candidates[:needed]

            if resolved_date is not None and len(selected) < needed:
                selected_ids = {
                    self._canonical_arxiv_id(getattr(result, "entry_id", "") or "")
                    for result in selected
                }
                fallback_candidates = self._qualified_for_date(
                    fallback_results,
                    resolved_date,
                    existing | {identifier for identifier in selected_ids if identifier},
                    require_relevance=True,
                )
                selected.extend(fallback_candidates[: needed - len(selected)])

        if resolved_date is None:
            print("未找到合格的 Video 论文发布日期", flush=True)
            return 0

        rows = [self._format_row(result) for result in selected]
        mode = "预览" if dry_run else "更新"
        print(
            f"{mode}日期 {resolved_date.isoformat()}：已有 {existing_count} 篇，"
            f"目标 {self.daily_results} 篇，选择新增 {len(rows)} 篇",
            flush=True,
        )
        for result in selected:
            canonical_id = self._canonical_arxiv_id(getattr(result, "entry_id", "") or "")
            print(f"  {canonical_id}: {getattr(result, 'title', '')}", flush=True)
        if not dry_run:
            self._append_rows(rows)
        return len(rows)

    def preview_daily(self, target_date: Optional[date] = None) -> int:
        return self.run_daily(target_date=target_date, dry_run=True)

    def initialize(self) -> int:
        return self.run_daily()


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("日期必须使用 YYYY-MM-DD 格式") from exc


def _default_papers_path() -> str:
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(scripts_dir), "papers.md")


def main() -> int:
    parser = argparse.ArgumentParser(description="按发布日期补足每日 Video arXiv 论文")
    parser.add_argument("--dry-run", action="store_true", help="真实搜索和筛选，但不修改 papers.md")
    parser.add_argument("--target-date", type=parse_date, help="只补指定发布日期，格式 YYYY-MM-DD")
    args = parser.parse_args()

    env_target = (os.getenv("ARXIV_TARGET_DATE") or "").strip()
    target_date = args.target_date or (parse_date(env_target) if env_target else None)
    collector = ArxivCollector(_default_papers_path())
    count = collector.run_daily(target_date=target_date, dry_run=args.dry_run)
    action = "预览可新增" if args.dry_run else "每日更新新增"
    print(f"{action} {count} 篇论文，数据文件: {collector.papers_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
