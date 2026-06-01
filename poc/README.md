# Self-Healing Scraper PoC

## Prerequisites

- Docker + `docker compose`
- Local `claude` CLI logged in (`claude --version` works)
- Python 3 (stdlib only)

## Commands

| Command | What it does |
| --- | --- |
| `make up` | Build & start `mock_site` + `scraper` containers AND launch `auto_healer.py` in the background (self-healing on by default). |
| `make logs` | Tail the scraper container output (`[runner] OK` / `[runner] FAIL`). |
| `make agent-logs` | Tail the host agent log (`failure detected` / `spawning claude` / `claude exited`). |
| `make v1` | Flip `mock_site` to v1 HTML (baseline — matches the seed scraper). |
| `make v2` | Flip to v2 HTML (BEM rename + JSON-LD) — breaks the seed scraper. |
| `make v3` | Flip to v3 HTML (web component + `data-*`) — breaks again. |
| `make reset` | Stop the stack + host agent, restore `seed/scraper.py`, clear logs. Run `make up` again to start fresh. |

The agent watches `workspace/failure.json`. When a failure appears, it spawns `claude -p ... --model='claude-opus-4-7[1M]' --dangerously-skip-permissions` in `workspace/` to patch the scraper.

## Play it

```
make up           # stack + agent, all in one
make v2           # break the scraper; agent auto-heals within ~30–60s
make v3           # try the harder one
```

Optional, in other terminals: `make logs` and `make agent-logs` to watch what's happening.

Open <http://localhost:8080> in a browser to see the current `mock_site` HTML — it changes every time you run `make v1` / `make v2` / `make v3`.

## Inspect

```
cat workspace/agent.log                       # agent events
diff seed/scraper.py workspace/scraper.py     # claude's patch
```

## ⚠️ Security note — PoC only

This PoC feeds the failed page's raw HTML into a `claude --dangerously-skip-permissions` invocation that can run `Bash` freely on the host. `mock_site` here serves static HTML we control, so it's safe.

**Do NOT point this at real third-party sites without sandboxing claude** (containerized, network-restricted, read-only host FS, no host credentials). A malicious page could embed prompt-injection payloads that the LLM would execute as host shell commands — turning an HTML response into RCE on the machine running `auto_healer.py`.
