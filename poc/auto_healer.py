"""Failure watcher that auto-triggers the local Claude Code CLI to heal the scraper.

When workspace/failure.json appears, this script spawns:

    claude -p "<prompt>" \
        --model='claude-opus-4-7[1M]' \
        --dangerously-skip-permissions

with cwd=workspace/, so Claude Code can Read scraper.py + failure.json, Edit
the scraper, and self-verify by running it inside the scraper container.
"""

import fcntl
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

POC_DIR = Path(__file__).resolve().parent
WORKSPACE = POC_DIR / "workspace"
FAILURE_PATH = WORKSPACE / "failure.json"
LOG_PATH = WORKSPACE / "agent.log"
LOCK_PATH = POC_DIR / ".agent.lock"

POLL_SECONDS = 3
CLAUDE_TIMEOUT_SECONDS = 600
MODEL = os.environ.get("AGENT_MODEL", "claude-opus-4-7[1M]")

PROMPT = """You are a self-healing scraper agent. The scraper in this directory (./scraper.py) just broke.

Context:
- cwd is the scraper's workspace (./scraper.py, ./failure.json, ./agent.log live here).
- A docker `scraper` container re-runs this scraper every 10s against http://mock_site (a docker-internal nginx). The container shares THIS directory as /workspace, so when you edit scraper.py the container picks it up on the next tick.
- From host, the same nginx is reachable at http://localhost:8080 (use this to inspect the live HTML with curl/WebFetch).
- Required deps (httpx, beautifulsoup4) only exist inside the container, not on host.

Steps:
1. Read scraper.py and failure.json. failure.json contains the raw HTML the scraper received plus the exception/trace.
2. Inspect the HTML to understand the new page structure. You can also `curl -s http://localhost:8080` to double-check the live markup.
3. Edit scraper.py to handle the new markup. Preserve the interface exactly:
   - Reads URL from sys.argv[1]
   - Prints a single JSON line on success with keys: title, price, sku, description (non-empty strings)
   - Writes failure.json next to the script on error
   - Exits 0 on success, 1 on failure
4. Verify by running inside the scraper container:
       docker compose -f ../docker-compose.yml exec -T scraper python /workspace/scraper.py http://mock_site
   (parent of cwd is the poc/ dir that holds docker-compose.yml). Exit 0 + valid JSON on stdout = success.
5. If it still fails, re-read failure.json (the container will have rewritten it) and iterate until the verify command succeeds.
6. Prefer robust selectors (multiple fallbacks, attribute-based, JSON-LD, data-* attrs) so this fix survives minor future markup tweaks.

Do not ask for confirmation; you have permission to Read, Edit, and Bash freely.
"""


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG_PATH.open("a") as f:
        f.write(line + "\n")


def run_claude() -> int:
    cmd = [
        "claude",
        "-p", PROMPT,
        "--model", MODEL,
        "--dangerously-skip-permissions",
    ]
    log(f"spawning claude ({MODEL}) in {WORKSPACE}")
    try:
        proc = subprocess.run(cmd, cwd=WORKSPACE, timeout=CLAUDE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        log(f"claude exceeded {CLAUDE_TIMEOUT_SECONDS}s timeout — killed")
        return -1
    log(f"claude exited with code {proc.returncode}")
    return proc.returncode


def handle_failure() -> None:
    log(f"failure detected at {FAILURE_PATH.name}")
    run_claude()
    if FAILURE_PATH.exists():
        log("failure.json still present after claude run — scraper may still be broken")
    else:
        log("failure.json gone — scraper fixed")


def acquire_lock():
    """Self-flock; second instance exits cleanly. Kernel releases lock on process death."""
    # mode "a+" so a failed second instance doesn't truncate the holder's PID.
    lock_fd = open(LOCK_PATH, "a+")
    try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_fd.close()
        print("auto-healer already running — exiting", flush=True)
        sys.exit(0)
    lock_fd.seek(0)
    lock_fd.truncate()
    lock_fd.write(f"{os.getpid()}\n")
    lock_fd.flush()
    return lock_fd  # caller must keep this fd alive


def main() -> None:
    if shutil.which("claude") is None:
        raise SystemExit("`claude` CLI not found in PATH. Install Claude Code first.")

    _lock_fd = acquire_lock()  # noqa: F841 — held for process lifetime

    LOG_PATH.write_text("")
    log(f"auto-healer up (pid {os.getpid()}), watching {FAILURE_PATH}")
    seen_mtime = 0.0
    while True:
        if FAILURE_PATH.exists():
            mtime = FAILURE_PATH.stat().st_mtime
            if mtime > seen_mtime:
                seen_mtime = mtime
                handle_failure()
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
