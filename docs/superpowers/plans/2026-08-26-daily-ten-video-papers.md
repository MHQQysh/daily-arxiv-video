# Daily Ten Video Papers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backfill 2026-08-25 to exactly 10 relevant Video papers and make future scheduled runs maintain up to 10 papers for the latest arXiv release date within a short, bounded search window.

**Architecture:** Keep the existing Markdown-backed site and downstream summary/image pipeline. Replace the one-shot five-result crawler with a date-aware, two-stage collector: a small `ti:video` query first, then an `all:video` fallback only when the target date remains below 10. Reuse the latest upstream repository's timeout, retry, dry-run, and workflow-trigger patterns while keeping Video-specific relevance rules and the current ModelScope summary provider.

**Tech Stack:** Python 3.9+, arxiv.py, requests, unittest, GitHub Actions, ModelScope-compatible OpenAI API, Playwright, PyMuPDF, GitHub Pages.

## Global Constraints

- Target exactly 10 papers per arXiv release date when at least 10 qualified papers exist.
- Preserve all current 60 curated Video papers; the 2026-08-25 backfill adds at most 7.
- Reject unrelated papers instead of filling the quota with noise.
- Use at most 30 primary candidates and 70 fallback candidates.
- Use one page per query, a 10-second HTTP timeout, two attempts, and a 5-second retry base.
- Set the GitHub Actions crawler step timeout to 3 minutes.
- Ordinary pushes perform a dry-run; schedules and explicitly authorized manual runs may modify `papers.md`.
- Keep the current ModelScope summary configuration unchanged.
- Repeated backfill runs must not duplicate papers or exceed 10 papers on the target date.

---

### Task 1: Video relevance policy

**Files:**
- Create: `scripts/video_topics.py`
- Test: `tests/test_video_topics.py`

**Interfaces:**
- Consumes: paper title and abstract strings from arxiv.py results.
- Produces: `PRIMARY_QUERY: str`, `FALLBACK_QUERY: str`, `ALLOWED_PRIMARY_CATEGORIES: set[str]`, `relevance_score(title: str, abstract: str) -> int`, and `is_relevant_video_paper(title: str, abstract: str) -> bool`.

- [ ] **Step 1: Write the failing relevance tests**

```python
class VideoTopicTests(unittest.TestCase):
    def test_title_video_is_always_relevant(self):
        self.assertTrue(is_relevant_video_paper("Efficient Video Reasoning", "A new benchmark."))

    def test_strong_abstract_topic_can_fill_fallback(self):
        abstract = "We study video generation and video diffusion with a temporal video model."
        self.assertTrue(is_relevant_video_paper("Efficient Temporal Models", abstract))

    def test_single_incidental_video_mention_is_rejected(self):
        self.assertFalse(is_relevant_video_paper("Image Classification", "A demo video is available."))
```

- [ ] **Step 2: Run the test and confirm the module is missing**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_video_topics -v
```

Expected: import failure for `scripts.video_topics`.

- [ ] **Step 3: Implement the Video policy**

Create constants and topic patterns for Video generation, understanding/reasoning, editing/control, analysis/perception, and data/representation. Score title `video/videos` as 5, each matched topic as 2 up to 6, and repeated abstract mentions as up to 2 more points. Accept title matches or scores of at least 4.

```python
PRIMARY_QUERY = "ti:video"
FALLBACK_QUERY = "all:video"

def is_relevant_video_paper(title: str, abstract: str) -> bool:
    if re.search(r"\bvideos?\b", title.lower()):
        return True
    return relevance_score(title, abstract) >= 4
```

- [ ] **Step 4: Run the relevance tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_video_topics -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit the policy**

```powershell
git add scripts/video_topics.py tests/test_video_topics.py
git commit -m "feat: define video paper relevance policy"
```

---

### Task 2: Date-aware bounded crawler

**Files:**
- Modify: `scripts/arxiv_crawler.py`
- Create: `tests/test_arxiv_crawler.py`

**Interfaces:**
- Consumes: constants and relevance functions from `scripts.video_topics.py`.
- Produces: `ArxivCollector.run_daily(target_date: Optional[date] = None, dry_run: bool = False) -> int`, CLI flags `--dry-run` and `--target-date YYYY-MM-DD`.

- [ ] **Step 1: Write failing crawler tests with synthetic arxiv results**

Use `types.SimpleNamespace` results with `entry_id`, `title`, `summary`, `primary_category`, `published`, and `updated`. Override `_search(query, max_results)` in a test collector so tests never contact arXiv.

Use these concrete helpers and assertions:

```python
def make_result(number, published_date, title=None, summary="video generation video diffusion video"):
    timestamp = datetime.combine(published_date, time(12), tzinfo=timezone.utc)
    return SimpleNamespace(
        entry_id=f"https://arxiv.org/abs/2608.{number:05d}v1",
        title=title or f"Video Paper {number}",
        summary=summary,
        primary_category="cs.CV",
        published=timestamp,
        updated=timestamp,
    )

class StubCollector(ArxivCollector):
    def __init__(self, papers_path, responses):
        super().__init__(
            papers_path,
            daily_results=10,
            primary_results=30,
            fallback_results=70,
        )
        self.responses = responses
        self.calls = []

    def _search(self, query, max_results):
        self.calls.append((query, max_results))
        return list(self.responses.get(query, []))

def test_target_date_with_three_existing_rows_adds_only_seven(self):
    target = date(2026, 8, 25)
    self.write_rows(target, range(1, 4))
    primary = [make_result(number, target) for number in range(4, 6)]
    fallback = [make_result(number, target) for number in range(4, 13)]
    collector = StubCollector(self.papers_path, {PRIMARY_QUERY: primary, FALLBACK_QUERY: fallback})
    self.assertEqual(collector.run_daily(target_date=target), 7)
    self.assertEqual(self.count_date(target), 10)

def test_target_date_with_ten_existing_rows_makes_no_request(self):
    target = date(2026, 8, 25)
    self.write_rows(target, range(1, 11))
    collector = StubCollector(self.papers_path, {})
    self.assertEqual(collector.run_daily(target_date=target), 0)
    self.assertEqual(collector.calls, [])

def test_fallback_query_runs_only_when_primary_cannot_fill_target(self):
    target = date(2026, 8, 25)
    self.write_rows(target, range(1, 8))
    primary = [make_result(number, target) for number in range(8, 11)]
    collector = StubCollector(self.papers_path, {PRIMARY_QUERY: primary})
    self.assertEqual(collector.run_daily(target_date=target), 3)
    self.assertEqual(collector.calls, [(PRIMARY_QUERY, 30)])

def test_unrelated_fallback_candidate_is_rejected(self):
    target = date(2026, 8, 25)
    self.write_rows(target, range(1, 4))
    unrelated = make_result(20, target, title="Image Classification", summary="A demo video is available.")
    collector = StubCollector(self.papers_path, {PRIMARY_QUERY: [], FALLBACK_QUERY: [unrelated]})
    self.assertEqual(collector.run_daily(target_date=target), 0)
    self.assertEqual(self.count_date(target), 3)

def test_other_dates_and_duplicate_ids_are_ignored(self):
    target = date(2026, 8, 25)
    self.write_rows(target, range(1, 4))
    duplicate = make_result(1, target)
    other_date = make_result(20, date(2026, 8, 24))
    qualified = make_result(21, target)
    collector = StubCollector(
        self.papers_path,
        {PRIMARY_QUERY: [], FALLBACK_QUERY: [duplicate, other_date, qualified]},
    )
    self.assertEqual(collector.run_daily(target_date=target), 1)
    self.assertEqual(self.count_date(target), 4)

def test_dry_run_returns_count_without_modifying_markdown(self):
    target = date(2026, 8, 25)
    self.write_rows(target, range(1, 4))
    before = self.papers_path.read_text(encoding="utf-8")
    primary = [make_result(number, target) for number in range(4, 11)]
    collector = StubCollector(self.papers_path, {PRIMARY_QUERY: primary})
    self.assertEqual(collector.run_daily(target_date=target, dry_run=True), 7)
    self.assertEqual(self.papers_path.read_text(encoding="utf-8"), before)

def test_request_session_applies_ten_second_timeout(self):
    session = _TimeoutSession(10)
    with patch.object(requests.Session, "request", return_value=object()) as request:
        session.request("GET", "https://export.arxiv.org/api/query")
    self.assertEqual(request.call_args.kwargs["timeout"], 10)
```

- [ ] **Step 2: Run crawler tests and confirm current behavior fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_arxiv_crawler -v
```

Expected: failures because the current collector has no target-date, fallback, timeout, or dry-run behavior.

- [ ] **Step 3: Add upstream-aligned request reliability**

Port the upstream `_TimeoutSession` pattern and initialize one arxiv client:

```python
class _TimeoutSession(requests.Session):
    def __init__(self, timeout_seconds: float):
        super().__init__()
        self.timeout_seconds = timeout_seconds

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", self.timeout_seconds)
        return super().request(method, url, **kwargs)
```

Read `ARXIV_REQUEST_TIMEOUT_SECONDS=10`, `ARXIV_MAX_RETRIES=2`, `ARXIV_RETRY_BASE_SECONDS=5`, and set the client page size large enough that each 30/70 candidate stage is one page.

- [ ] **Step 4: Implement existing-date counts and canonical IDs**

Add a parser that returns both existing canonical IDs and `Counter[str]` date counts. Normalize versioned arXiv IDs and both HTTP/HTTPS links before deduplication.

```python
def _load_existing_state(self) -> tuple[set[str], Counter[str]]:
    identifiers: set[str] = set()
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
```

- [ ] **Step 5: Implement two-stage target-date selection**

Behavior:

1. If an explicit target date already has 10 rows, return 0 before network access.
2. Search 30 `ti:video` candidates.
3. Use the explicit target date or the newest allowed primary-result date.
4. Keep new primary candidates from that date.
5. Only when existing plus primary is below 10, search 70 `all:video` candidates.
6. Filter fallback candidates with `is_relevant_video_paper`.
7. Add only `10 - existing_count` rows.
8. In dry-run, print the selected IDs and return the count without writing.

- [ ] **Step 6: Add CLI flags**

```python
parser.add_argument("--dry-run", action="store_true")
parser.add_argument("--target-date", type=parse_date)
```

An empty `ARXIV_TARGET_DATE` means automatic newest-date behavior; a CLI date takes precedence.

- [ ] **Step 7: Run all crawler and topic tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_video_topics tests.test_arxiv_crawler -v
```

Expected: all pass.

- [ ] **Step 8: Commit the crawler**

```powershell
git add scripts/arxiv_crawler.py tests/test_arxiv_crawler.py
git commit -m "feat: keep ten video papers per release date"
```

---

### Task 3: Bounded GitHub Actions configuration and documentation

**Files:**
- Modify: `.github/workflows/deploy.yml`
- Modify: `tests/test_workflows.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: crawler CLI from Task 2.
- Produces: scheduled real updates, manual target-date backfills, and push dry-runs.

- [ ] **Step 1: Extend the workflow contract tests**

Assert `deploy.yml` contains:

```text
timeout-minutes: 3
ARXIV_DAILY_RESULTS: 10
ARXIV_PRIMARY_RESULTS: 30
ARXIV_FALLBACK_RESULTS: 70
ARXIV_REQUEST_TIMEOUT_SECONDS: 10
ARXIV_MAX_RETRIES: 2
ARXIV_RETRY_BASE_SECONDS: 5
python -u scripts/arxiv_crawler.py --dry-run
```

Also assert workflow-dispatch inputs include `add_new_papers` and `target_date`, while the schedule path executes a real update.

- [ ] **Step 2: Run the workflow test and confirm it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_workflows -v
```

Expected: failures against the current five-result workflow.

- [ ] **Step 3: Update the workflow**

Add manual inputs and use this trigger rule:

```yaml
if [ "${{ github.event_name }}" = "schedule" ] || { [ "${{ github.event_name }}" = "workflow_dispatch" ] && [ "${{ inputs.add_new_papers }}" = "true" ]; }; then
  python -u scripts/arxiv_crawler.py
else
  python -u scripts/arxiv_crawler.py --dry-run
fi
```

Pass `${{ inputs.target_date }}` through `ARXIV_TARGET_DATE`, add a 3-minute crawler timeout, and run the unit-test suite before network work.

- [ ] **Step 4: Correct README defaults and behavior**

Document that 10 is a per-release-date target, 30/70 are candidate pools rather than output counts, broad fallback is conditional, push is dry-run, and scheduled/manual authorized runs write data.

- [ ] **Step 5: Validate YAML and run all tests**

Run:

```powershell
.\.venv\Scripts\python.exe -c "import pathlib,yaml; yaml.safe_load(pathlib.Path('.github/workflows/deploy.yml').read_text(encoding='utf-8')); print('workflow yaml: ok')"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected: YAML parses and all tests pass.

- [ ] **Step 6: Commit workflow and docs**

```powershell
git add .github/workflows/deploy.yml tests/test_workflows.py README.md
git commit -m "ci: bound daily video paper updates"
```

---

### Task 4: Live dry-run and 2026-08-25 backfill

**Files:**
- Modify through workflow: `papers.md`
- Regenerate through workflow: `site/`

**Interfaces:**
- Consumes: Task 3 workflow inputs.
- Produces: 67-paper repository with exactly 10 papers dated 2026-08-25.

- [ ] **Step 1: Run a timed local dry-run**

```powershell
Measure-Command {
  .\.venv\Scripts\python.exe scripts/arxiv_crawler.py --dry-run --target-date 2026-08-25
}
```

Expected: seven selected IDs, no file change, no more than two arXiv query stages, and elapsed time below 3 minutes.

- [ ] **Step 2: Verify the repository remains unchanged after dry-run**

```powershell
git status --short
```

Expected: clean working tree.

- [ ] **Step 3: Push implementation commits**

```powershell
git push origin master
```

- [ ] **Step 4: Dispatch the full workflow with explicit authorization**

Dispatch `deploy.yml` at `master` with:

```json
{
  "ref": "master",
  "inputs": {
    "add_new_papers": "true",
    "target_date": "2026-08-25"
  }
}
```

The workflow adds the seven rows, generates ModelScope summaries, downloads images, builds the site, commits generated content, and deploys Pages.

- [ ] **Step 5: Monitor every workflow step**

Expected successful steps: unit tests, arXiv crawler, summaries, direct images, Playwright fallback, PDF fallback, site build, generated-content commit, artifact upload, and Pages deploy.

- [ ] **Step 6: Pull the generated commit**

```powershell
git pull --ff-only origin master
```

Expected: local HEAD advances to the workflow-generated commit.

---

### Task 5: Final local and online verification

**Files:**
- Verify: `papers.md`
- Verify: `site/assets/data.json`
- Verify: `site/assets/paper-images.json`

**Interfaces:**
- Consumes: generated repository state from Task 4.
- Produces: measured delivery evidence.

- [ ] **Step 1: Verify paper counts and uniqueness**

Check that total rows are 67, `2026-08-25` has 10 rows, all arXiv IDs are unique, and no inherited non-Video rows returned.

- [ ] **Step 2: Verify summaries and image manifests**

Assert no 2026-08-25 row contains `待生成`, all 67 IDs have usable manifest entries, and all local full/thumbnail image files exist and decode.

- [ ] **Step 3: Verify online data and representative images**

Fetch the deployed `assets/data.json` and `assets/paper-images.json` with cache-busting. Require 67 records, 10 for 2026-08-25, and HTTP 200 `image/webp` for every newly added full image and thumbnail.

- [ ] **Step 4: Verify Git state**

```powershell
git status --short --branch
git rev-parse HEAD
git ls-remote origin refs/heads/master
```

Expected: clean tree and identical local/remote SHA.

- [ ] **Step 5: Report measured runtime and upstream differences**

Report the actual dry-run duration, whether fallback was needed, added IDs, final counts, test count, workflow run URL, site URL, and the distinction between source-code changes and generated-site churn.
