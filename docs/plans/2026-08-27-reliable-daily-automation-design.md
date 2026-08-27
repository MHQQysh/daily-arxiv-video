# Reliable Daily Video Automation Design

## Goal

Make the repository start its Video update automatically every day, keep up to ten relevant papers for the latest arXiv release date, and prevent an older workflow run from replacing a newer deployed site.

## Confirmed failures

1. The manual backfill used `target_date=2026-08-25`, so it intentionally did not process 2026-08-26.
2. No `schedule` event was created for the first expected daily run. The cron ran at minute zero, a documented GitHub Actions congestion point.
3. A queued push workflow built from the older `dd7316800` event SHA after the successful backfill. It uploaded the old 60-paper site artifact and replaced the newer deployment, although `origin/master` still contained 67 papers.
4. The homepage requests `assets/data.json` at a stable URL, so browser and Pages caches can delay visibility after a deployment.

## Chosen architecture

Split mutation from ordinary publication:

- `.github/workflows/deploy.yml` becomes the updater. It runs only on `schedule` and `workflow_dispatch`, performs the bounded arXiv crawl, summaries, image recovery, site build, commit, and Pages deployment.
- `.github/workflows/publish-site.yml` publishes the already generated `site/` directory on ordinary pushes and manual dispatches. It never crawls or rewrites papers.
- Both workflows use the same concurrency group with `cancel-in-progress: true`. A newer update or publication cancels an obsolete run instead of allowing the obsolete artifact to deploy later.

The permanent daily schedule is 12:17 Asia/Shanghai (`17 4 * * *` in UTC). Minute 17 avoids the top-of-hour congestion window.

## Data freshness

The generated homepage app requests `assets/data.json` with a per-request cache-busting query parameter and `cache: 'no-store'`. This prevents an otherwise healthy deployment from continuing to display an older data payload.

## Verification strategy

1. Add regression tests for trigger separation, shared concurrency cancellation, minute-17 daily scheduling, and cache-busted data loading.
2. Run all unit tests and parse every workflow YAML file.
3. Add a temporary near-future non-zero-minute cron entry and push it.
4. Wait for a real GitHub `schedule` event. The scheduled run must select and add ten 2026-08-26 Video papers without manual dispatch.
5. Verify the run succeeds, its generated commit is on `origin/master`, and the online site shows ten papers for both 2026-08-25 and 2026-08-26 with usable images.
6. Remove the temporary verification cron, leaving only the permanent daily 12:17 schedule, then verify the final remote workflow configuration.

## Failure behavior

- arXiv requests remain bounded by the existing 10-second request timeout, two attempts, two query stages, and three-minute crawler step timeout.
- If ModelScope has insufficient balance, papers and images still update while summaries remain visibly pending; the run must not fabricate summaries.
- A stale or cancelled run must never deploy after a newer run.

