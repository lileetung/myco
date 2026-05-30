# Self-Healing Scraper System — Plan

## Goal

A scraper system where fixed scraper code is the primary path, and when a scrape
fails the LLM agent edits the scraper source, opens a PR, auto-merges if CI
passes, and triggers a blue-green redeploy. State (queue, data, code, patch
history) survives container restarts.

## Design influences

- **Scry (mayflower/scry):** IR + constrained patches + LLM-at-build-time,
  deterministic-at-runtime. We're rejecting the constrained-patch model in
  favor of free LLM source edits, but keeping "agent fixes code, runtime has
  no LLM."
- **Anansi (mdowis/anansi):** SQLite-backed persistent queue, confidence-scored
  selectors, pause/resume across process restarts, deterministic healing layers
  before any agent involvement. We're keeping the persistence pattern (in
  Postgres instead of SQLite) but skipping deterministic healing — every
  failure goes straight to the agent.
- **welly-geo-backend:** the entire blue-green runtime, nginx envsubst
  template, `deploy.sh` flip+rollback, status JSON, GitHub Actions CD pattern.
  Reused as-is.

## Architecture

```
                     ┌─────────────────────────────────┐
                     │   GitHub repo: crawler-scrapers │
                     │   main = live scraper code      │
                     └──────────────┬──────────────────┘
                                    │  push to main (after PR merge)
                                    ▼
                     ┌─────────────────────────────────┐
                     │   .github/workflows/cd_dev.yml  │
                     │   → ssh → deploy.sh (existing)  │
                     └──────────────┬──────────────────┘
                                    ▼
   ┌──────────┐    ┌──────────┐    ┌──────────────┐    ┌──────────────┐
   │  nginx   │───►│ scraper_ │    │  scraper_    │    │  Postgres    │
   │          │    │  blue    │    │  green       │    │              │
   │ envsubst │    │ (active) │    │ (standby)    │    │  items       │
   └──────────┘    └────┬─────┘    └──────────────┘    │  failures    │
                        │                              │  patches     │
                        ▼                              │  runs        │
                   ┌──────────┐                        └──────────────┘
                   │  worker  │◄──── Redis (URL queue + fp dedup)
                   │ dispatch │
                   └────┬─────┘
                        │ scrape failure event
                        ▼
                   ┌──────────────────────────────────────────┐
                   │  agent service                            │
                   │  1. fingerprint failure                   │
                   │  2. dedup vs Redis + Postgres `failures`  │
                   │  3. if new: clone repo, branch, LLM edit, │
                   │     trigger CI, push, open PR             │
                   │  4. CI green → auto-merge → CD fires      │
                   └──────────────────────────────────────────┘
```

## Components

### Reused from welly-geo-backend (no changes needed)

| welly-geo piece                     | Role in scraper system                   |
| ----------------------------------- | ---------------------------------------- |
| `nginx` + envsubst template         | Routes scraper API to blue/green         |
| `backend_blue` / `backend_green`    | Rename → `scraper_blue` / `scraper_green` |
| `redis`                             | URL queue + fingerprint dedup window     |
| `db` (pgvector pg15)                | Items, failures, patches, runs           |
| `db-migration`                      | Alembic on scraper schema                |
| `deploy.sh` (blue-green + rollback) | Runs after PR merge; no edits needed     |
| `cd_dev.yml` GitHub Actions         | SSH → `deploy.sh`                        |
| Status JSON pattern                 | Tracks active scraper version            |

### New components

- **scraper_blue / scraper_green** — the actual scraper service. Pulls URLs
  from Redis, scrapes, writes items to Postgres. Emits failure events on
  exceptions.
- **worker (dispatcher)** — same shape as welly-geo's worker. Pulls URLs from
  Redis, dispatches to whichever scraper is active. Also listens for failure
  events and routes to the agent service.
- **agent service** — new container. Watches a failure queue, runs the
  fingerprint → dedup → patch → PR pipeline.

## Failure flow (concrete)

1. **scraper_blue** fails on `example.com/products/42`. Emits failure event:
   ```
   {
     scraper: "shop",
     error_class: "SelectorNotFound",
     selector: ".price",
     html_hash: "abc123",
     url_pattern: "/products/*",
     trace: "...",
     html_snapshot_ref: "s3://..."
   }
   ```
   Writes to Postgres `failures`, pushes fingerprint to Redis
   `fp:shop:SelectorNotFound:abc123` with 5-min TTL.

2. **Dispatcher** consumes the failure event. Checks fingerprint:
   - **In Redis (recently seen)?** → drop, increment counter on existing
     `failures` row. No agent call.
   - **Already an open auto-fix PR for this scraper?** → drop, link failure
     to existing PR.
   - **Truly new?** → enqueue agent job.

3. **Agent service**:
   - `git clone` scraper repo, branch `auto-fix/shop/<fp-prefix>-<ts>`
   - LLM prompt includes:
     - current scraper source for the failing site
     - error trace + failed HTML snapshot + URL
     - **last 5 merged patches for this scraper (and rejected ones)**
     - last successful output sample for the same URL pattern
   - LLM edits source, commits, pushes
   - Opens PR with structured body (fingerprint, failure count, prior patches,
     diff reasoning)

4. **CI** (new `.github/workflows/ci_scraper.yml`) runs on the PR:
   - Replays patched scraper against **golden fixture HTML** for that scraper
   - Validates output against Pydantic schema for that scraper
   - Optional: runs against 5 live URLs sampled from the production failure set
   - All green → auto-merge enabled

5. **Auto-merge** → push to main → `cd_dev.yml` fires → `deploy.sh` swaps
   blue/green for the scraper service. Old version stays warm for rollback.

6. **Post-deploy watch**: dispatcher monitors error rate for N minutes
   post-deploy. If error rate spikes past threshold → calls
   `deploy.sh rollback`.

## Data model (Postgres)

```
failures
  id              uuid pk
  scraper         text
  fingerprint     text         -- dedup key
  error_class     text
  selector        text null
  html_hash       text
  html_snapshot   text         -- s3 ref or large text
  url             text
  url_pattern     text
  trace           text
  count           int          -- bumped on each dup
  first_seen      timestamptz
  last_seen       timestamptz
  linked_patch_id uuid null fk patches.id
  status          text         -- open | patched | wontfix

patches
  id              uuid pk
  scraper         text
  branch          text
  pr_url          text
  fingerprint     text
  ci_status       text         -- pending | green | red
  merged_at       timestamptz null
  reverted_at     timestamptz null
  llm_diff        text
  llm_reasoning   text
  prior_patch_ids uuid[]       -- chain visible to next agent run

runs
  id              uuid pk
  scraper         text
  version_sha     text         -- git sha live at start
  started_at      timestamptz
  ended_at        timestamptz null
  pages_ok        int
  pages_fail      int
  error_rate      float
```

`failures.fingerprint` is the dedup key. `patches.fingerprint` lets the next
agent run see "we already tried fixing this exact fingerprint — here's what
worked or didn't."

## Auto-merge safety: golden fixtures

This is the load-bearing piece of the whole design. Auto-merge is only safe if
CI is meaningful.

**Mechanism:** every successful scraper run snapshots its result:
- `fixtures/<scraper>/<url-hash>.html` — raw HTML
- `fixtures/<scraper>/<url-hash>.json` — extracted output

CI replays these on every PR: patched scraper must extract the same output
from the same HTML, modulo a tolerated diff (e.g. timestamps, price drift
within tolerance).

The fixture set grows automatically from real production successes. No human
curation needed beyond the first few seed fixtures per scraper.

**Acceptance gate for auto-merge:**
- 100% golden fixture replay pass
- Pydantic schema valid on all extracted output
- Optional: 5 live-URL replays from the production failure set must extract
  non-empty output of the right shape

## Auto-rollback

Dispatcher watches error rate in a sliding window post-deploy. Triggers:

- Error rate > 30% in first 5 minutes post-deploy, OR
- First 10 consecutive failures post-deploy

→ Calls `deploy.sh rollback`. Marks the responsible `patches` row as
`reverted_at = now()`. Next agent run for that scraper sees the reverted patch
in its prior-patches context.

## Per-scraper concurrency

**Max 1 open auto-fix PR per scraper.** If a second failure with a different
fingerprint arrives while a PR is open:
- Write the failure to `failures` table (so it's not lost).
- Do **not** spawn a second agent run for that scraper.
- When the open PR merges or closes, dispatcher re-scans `failures` for that
  scraper and may trigger a fresh agent run on the highest-count open failure.

This prevents thrash from parallel PRs touching overlapping code.

## Decisions made (record)

| Decision                           | Choice                            |
| ---------------------------------- | --------------------------------- |
| Agent trigger                      | Every failure                     |
| Patch scope                        | Free LLM edits to scraper source  |
| Code source of truth               | Git, PR-per-fix                   |
| Queue source of truth              | Redis                             |
| Data source of truth               | Postgres                          |
| Deploy model                       | Blue-green (reuse welly-geo)      |
| PR merge policy                    | Auto-merge if CI green            |
| Failure dedup                      | Fingerprinting (error+selector+html_hash) |
| Max open PRs per scraper           | 1                                 |

## Decisions deferred to implementation

- **Failure fingerprint formula.** Starting point: `hash(scraper + error_class
  + selector + html_structure_hash)`. May need tuning once we see real
  distributions.
- **Rollback thresholds.** 30% / 5 min and 10-consecutive are first guesses.
- **Live-URL replay count in CI.** 5 is a guess; balance signal vs CI runtime.
- **Golden fixture pruning.** Fixtures grow forever otherwise. Probably:
  prune fixtures > N days old when a newer fixture exists for the same
  url-hash.
- **Agent service runtime.** Long-running container vs spawn-per-failure.
  Long-running probably wins (warm git clones, cached LLM client) but
  isolation per job matters too.
- **Multi-site scope.** One scraper repo with many scrapers, or one repo per
  scraper. One repo simpler; one-per-scraper isolates blast radius.

## Risks to revisit after first weeks of operation

- **Runaway patching.** Same scraper patched repeatedly without converging.
  Mitigation: cap auto-fix PRs per scraper per 24h; force human review past
  threshold.
- **LLM cost.** Every failure invokes the LLM. Mitigation: dedup is the
  primary lever; consider a cheap pre-classifier that drops obvious transient
  failures (network timeout, 5xx) before agent invocation.
- **Golden fixture rot.** Fixtures captured today may not represent the site
  next month. Auto-prune + periodic refresh from live successes.
- **CI false-greens.** Golden fixtures pass but real production fails.
  Mitigation: post-deploy error-rate watch + auto-rollback is the backstop.
- **Race: deploy mid-crawl.** Worker holds in-flight URLs when blue→green
  flips. Mitigation: graceful worker drain (Anansi pause/resume pattern) or
  accept that in-flight URLs get re-queued after timeout.
