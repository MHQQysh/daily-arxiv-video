# Reliable Daily Video Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Video site update automatically every day, prevent stale workflow deployments, and prove the mechanism by automatically adding ten 2026-08-26 papers.

**Architecture:** Separate the mutating scheduled updater from the push-triggered publish-only workflow. Both workflows share a cancelling concurrency group, while the homepage bypasses stale `data.json` caches. A temporary near-future cron provides end-to-end evidence before the permanent daily-only schedule is restored.

**Tech Stack:** GitHub Actions YAML, Python 3.9, `unittest`, vanilla JavaScript, Playwright, GitHub REST API.

## Global Constraints

- Permanent schedule: every day at 12:17 Asia/Shanghai, represented as `17 4 * * *` UTC.
- Daily target: ten relevant Video papers per newest arXiv release date.
- Crawler bounds: 10-second request timeout, two attempts, primary 30 candidates, fallback 70 candidates, three-minute crawler step timeout.
- Push workflows must never crawl or rewrite `papers.md`.
- A stale workflow run must never deploy after a newer run.
- The temporary verification cron must be removed after a real `schedule` event succeeds.

---

### Task 1: Separate updater and publisher triggers

**Files:**
- Modify: `.github/workflows/deploy.yml`
- Modify: `.github/workflows/publish-site.yml`
- Test: `tests/test_workflows.py`

**Interfaces:**
- Consumes: existing `deploy.yml` updater pipeline and `publish-site.yml` artifact publisher.
- Produces: schedule/manual-only updater and push/manual-only publisher with shared cancellation.

- [ ] **Step 1: Write failing workflow contract tests**

Add assertions equivalent to:

```python
def test_updater_is_schedule_or_manual_only_and_avoids_top_of_hour(self):
    content = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    self.assertIn("cron: '17 4 * * *'", content)
    self.assertNotIn("push:\n", content)
    self.assertIn('group: "daily-video-pages"', content)
    self.assertIn("cancel-in-progress: true", content)

def test_publish_only_handles_push_without_mutating_data(self):
    content = (ROOT / ".github/workflows/publish-site.yml").read_text(encoding="utf-8")
    self.assertIn("push:\n", content)
    self.assertIn('group: "daily-video-pages"', content)
    self.assertIn("cancel-in-progress: true", content)
    self.assertNotIn("arxiv_crawler.py", content)
    self.assertNotIn("git push", content)
```

- [ ] **Step 2: Run tests and confirm they fail**

Run: `python -m unittest tests.test_workflows -v`

Expected: failures for the minute-zero schedule, updater push trigger, missing publisher push trigger, and missing cancelling concurrency.

- [ ] **Step 3: Implement the workflow split**

In `deploy.yml`, remove the `push` trigger, retain `workflow_dispatch` and `schedule`, change the permanent cron to `17 4 * * *`, and simplify the crawler condition so schedule or `add_new_papers=true` performs the real crawl. Add:

```yaml
concurrency:
  group: "daily-video-pages"
  cancel-in-progress: true
```

In `publish-site.yml`, add push branches `master` and `main` plus the same concurrency block. Keep it read-only and free of crawler, summary, image, and git-push steps.

- [ ] **Step 4: Run the workflow tests**

Run: `python -m unittest tests.test_workflows -v`

Expected: all workflow contract tests pass.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/deploy.yml .github/workflows/publish-site.yml tests/test_workflows.py
git commit -m "fix: make daily updater race safe"
```

### Task 2: Bypass stale homepage data caches

**Files:**
- Modify: `scripts/build_site.py:2462-3290`
- Create: `tests/test_build_site.py`
- Regenerate: `site/assets/app.js`

**Interfaces:**
- Consumes: `generate_app_js() -> str`.
- Produces: app JavaScript that fetches `assets/data.json` through a unique query URL with browser caching disabled.

- [ ] **Step 1: Write the failing cache regression test**

```python
from scripts.build_site import generate_app_js

def test_homepage_data_fetch_bypasses_stale_cache(self):
    app_js = generate_app_js()
    self.assertIn("assets/data.json?v=", app_js)
    self.assertIn("cache: 'no-store'", app_js)
    self.assertIn("Date.now()", app_js)
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `python -m unittest tests.test_build_site -v`

Expected: FAIL because the current app uses the stable `assets/data.json` URL.

- [ ] **Step 3: Implement cache-busted loading**

Replace the stable fetch with:

```javascript
const dataURL = `assets/data.json?v=${Date.now()}`;
const response = await fetch(dataURL, { cache: 'no-store' });
```

- [ ] **Step 4: Regenerate and verify site assets**

Run: `python scripts/build_site.py`

Run: `python -m unittest tests.test_build_site -v`

Expected: the test passes and generated `site/assets/app.js` contains the cache-busted request.

- [ ] **Step 5: Commit**

```bash
git add scripts/build_site.py tests/test_build_site.py site
git commit -m "fix: bypass stale paper data caches"
```

### Task 3: Validate locally and publish a temporary schedule probe

**Files:**
- Temporarily modify: `.github/workflows/deploy.yml`

**Interfaces:**
- Consumes: hardened workflows and cache-busted site.
- Produces: a near-future non-zero-minute cron entry that exercises the exact schedule event path.

- [ ] **Step 1: Run the complete local verification**

Run: `python -m unittest discover -s tests -v`

Run: parse all `.github/workflows/*.yml` with `yaml.safe_load`.

Run: `git diff --check`.

Expected: all tests and YAML checks pass with no whitespace errors.

- [ ] **Step 2: Choose a verification minute**

Read current UTC time and select a non-zero minute at least ten minutes in the future. Add a second temporary cron line for that time while retaining `17 4 * * *`.

- [ ] **Step 3: Commit and push the probe**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: add temporary daily schedule probe"
git push origin master
```

- [ ] **Step 4: Confirm ordinary push does not invoke the updater**

Use the GitHub Actions API. Expected: `publish-site.yml` gets a push run; `deploy.yml` does not get a push run.

### Task 4: Prove automatic 2026-08-26 update

**Files:**
- Generated by workflow: `papers.md`, `site/assets/data.json`, `site/assets/paper-images.json`, paper images, thumbnails, and paper pages.

**Interfaces:**
- Consumes: temporary schedule event and automatic date selection in `scripts/arxiv_crawler.py`.
- Produces: a successful `schedule` run and ten 2026-08-26 papers without manual dispatch.

- [ ] **Step 1: Wait for the real schedule event**

Poll the workflow API until a new run has `event=schedule`. Do not manually dispatch the updater.

- [ ] **Step 2: Inspect every workflow phase**

Expected successful steps: tests, bounded arXiv crawl, summary attempt, image pipeline, site build, generated commit, artifact upload, and Pages deployment.

- [ ] **Step 3: Pull the generated commit**

Run: `git pull --ff-only origin master`.

Expected: ten new 2026-08-26 rows and image artifacts arrive from the scheduled run.

- [ ] **Step 4: Verify repository invariants**

Check:

```text
2026-08-25 count = 10
2026-08-26 count = 10
all arXiv IDs unique
site data count equals papers count
manifest count equals papers count
all ten new full images and thumbnails exist and decode
```

### Task 5: Remove the temporary probe and verify final state

**Files:**
- Modify: `.github/workflows/deploy.yml`

**Interfaces:**
- Consumes: successful schedule evidence.
- Produces: final permanent daily-only schedule at 12:17 Asia/Shanghai.

- [ ] **Step 1: Remove only the temporary cron line**

Leave:

```yaml
schedule:
  - cron: '17 4 * * *'
```

- [ ] **Step 2: Run workflow tests and YAML parsing again**

Expected: all tests pass and only one schedule remains.

- [ ] **Step 3: Commit and push the final schedule**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: keep permanent daily video schedule"
git push origin master
```

- [ ] **Step 4: Verify final remote and online state**

Confirm through the GitHub API and live browser:

```text
deploy workflow active
default branch master
exact permanent cron 17 4 * * *
shared cancel-in-progress concurrency in both workflows
online total equals remote data total
online 2026-08-25 count = 10
online 2026-08-26 count = 10
online ten new full images and thumbnails return HTTP 200 and decode
```

- [ ] **Step 5: Record completion**

Only after every check above passes, mark the active goal complete.

