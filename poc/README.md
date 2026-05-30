# Self-Healing Scraper PoC

Three containers exercising the agent-patches-scraper loop end-to-end:

- **`mock_site`** — nginx serving a static product page. Three HTML versions in `mock_site/html/v1|v2|v3` are bind-mounted one at a time via `SITE_VERSION`.
- **`scraper`** — Python service that runs `workspace/scraper.py` against the mock site every 10s. On failure, writes `workspace/failure.json`.
- **`agent`** — long-running watcher. When it sees `failure.json`, sends the scraper source + error + raw HTML to Claude, applies the returned patched source, runs the scraper itself to verify, and commits to a local git repo in `workspace/` on success.

`workspace/` is bind-mounted into both `scraper` and `agent`, so the agent's edits are immediately visible to the scraper's next run.

## Setup

```
cp .env.example .env
# Edit .env: set CLAUDE_API_KEY
make up
make logs
```

Initial state is `SITE_VERSION=v1`. You should see, every 10s:

```
scraper-1  | [runner] OK  {"title": "Acme Widget Pro", "price": "$49.99", ...}
agent-1    | [HH:MM:SS] agent up, watching /workspace/failure.json
```

## Trigger a patch

Flip the mock site to a version with different markup:

```
make v2     # rename CSS classes (.price → .product-price, etc.)
```

What you'll see:

1. Within ~10s the scraper logs `[runner] FAIL`.
2. `workspace/failure.json` appears.
3. The agent logs `failure detected`, `calling Claude`, `patched scraper.py`, `verification PASSED`.
4. The scraper's next iteration logs `[runner] OK` again.

Then try the harder one:

```
make v3     # restructure DOM to <article data-*>
```

## Inspect what the agent did

```
cd workspace
git log --oneline
git diff HEAD~1 HEAD -- scraper.py
cat agent.log
```

## Reset

```
make reset       # revert scraper.py and clear failure log
make v1     # back to the original site
```

## How the test versions differ

| Version | Style | What changes for the scraper |
| --- | --- | --- |
| **v1** | 2015-era e-commerce — semantic classes, Bootstrap-ish layout | baseline: `h1.product-title`, `.price` (with `$` prefix), `.sku` (with `SKU: ` prefix), `.description` |
| **v2** | Modern BEM redesign with structured data | classes fully renamed (`pdp__name`, `pdp__pricing__amount`, etc.); price split into amount + currency nodes (no `$`); SKU lives inside `<dl><dt>SKU</dt><dd>WGT-001</dd></dl>`; full JSON-LD + Open Graph available as a clean alternate data source |
| **v3** | Headless / SPA shell with web components | uses a `<product-card>` custom element; price and SKU are in `data-*` attributes, NOT in visible DOM text (the rendered `$49.99` is injected by CSS `::before`); product name appears both in `data-product-name` and in a `<header>` inside `[data-slot="content"]`; description is the only field still in a plain `<p>` |

Open `http://localhost:8080` in a browser after each flip — you'll see they actually look like three different sites.

## What this PoC is and isn't

This is the minimum end-to-end loop. It deliberately skips:

- Blue-green deployment of the scraper (here, the next loop iteration just picks up the new code).
- Postgres / Redis for queue + items (no queue at all — single URL, in-memory).
- nginx routing and the welly-geo-style `deploy.sh` flip.
- GitHub PRs and CI gating (commits go to a local-only git in `workspace/.git`).
- Failure fingerprint dedup across multiple sites (one scraper, one site).
- Golden-fixture replay verification (verification = "the patched scraper exits 0").

See `../PLAN.md` for the full production design these are placeholders for.
