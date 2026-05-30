import json
import os
import subprocess
import time
from pathlib import Path

from anthropic import Anthropic

WORKSPACE = Path("/workspace")
SCRAPER_PATH = WORKSPACE / "scraper.py"
FAILURE_PATH = WORKSPACE / "failure.json"
LOG_PATH = WORKSPACE / "agent.log"

MAX_ATTEMPTS = 5
POLL_SECONDS = 3
URL = os.environ.get("SCRAPER_URL", "http://mock_site")
MODEL = os.environ.get("AGENT_MODEL", "claude-sonnet-4-6")

client = Anthropic(api_key=os.environ["CLAUDE_API_KEY"])

SYSTEM_PROMPT = """You are a self-healing scraper agent. Each turn you receive:
1. The current source of a Python scraper using httpx + BeautifulSoup.
2. A failure record describing why it just broke (exception class, message, trace).
3. The raw HTML of the page the scraper was trying to scrape.

Your job: produce a corrected version of the scraper that will succeed against that HTML.

Strict output rules:
- Output ONLY the complete corrected Python source. No prose, no explanations, no markdown fences.
- Preserve the script interface: reads URL from argv[1], writes /workspace/failure.json on error, prints a single JSON object on success, exits 0 on success and 1 on failure.
- Keep the same output schema keys: title, price, sku, description.
- Prefer selectors that survive minor markup variations (e.g. multiple fallback selectors, attribute-based selectors, robust text extraction).
"""


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG_PATH.open("a") as f:
        f.write(line + "\n")


def strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines)
    return t.strip() + "\n"


def call_claude(scraper_src: str, failure: dict) -> str:
    failure_for_prompt = {k: v for k, v in failure.items() if k != "html"}
    html = failure.get("html") or "(no HTML captured)"

    user_message = (
        "Current scraper source:\n"
        "```python\n"
        f"{scraper_src}"
        "```\n\n"
        "Failure record:\n"
        "```json\n"
        f"{json.dumps(failure_for_prompt, indent=2)}\n"
        "```\n\n"
        "Raw HTML the scraper received:\n"
        "```html\n"
        f"{html}\n"
        "```\n\n"
        "Produce the corrected complete scraper.py source."
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return strip_fences(response.content[0].text)


def verify_scraper() -> tuple[bool, str]:
    proc = subprocess.run(
        ["python", str(SCRAPER_PATH), URL],
        capture_output=True,
        text=True,
        timeout=30,
    )
    out = (proc.stdout or proc.stderr).strip()
    return proc.returncode == 0, out


def handle_failure() -> None:
    if not FAILURE_PATH.exists():
        return
    failure = json.loads(FAILURE_PATH.read_text())
    fingerprint = failure.get("error_class", "?")
    log(f"failure detected: {fingerprint} — {failure.get('error_message','')[:140]}")

    for attempt in range(1, MAX_ATTEMPTS + 1):
        log(f"attempt {attempt}/{MAX_ATTEMPTS}: calling Claude ({MODEL})")
        scraper_src = SCRAPER_PATH.read_text()
        try:
            new_src = call_claude(scraper_src, failure)
        except Exception as e:
            log(f"  Claude call failed: {e}")
            time.sleep(5)
            continue

        SCRAPER_PATH.write_text(new_src)
        log(f"  patched scraper.py ({len(new_src)} bytes)")

        ok, out = verify_scraper()
        if ok:
            log(f"  verification PASSED → {out[:200]}")
            FAILURE_PATH.unlink(missing_ok=True)
            return

        log(f"  verification FAILED → {out[:200]}")
        if FAILURE_PATH.exists():
            failure = json.loads(FAILURE_PATH.read_text())

    log(f"giving up after {MAX_ATTEMPTS} attempts")


def main() -> None:
    log(f"agent up, watching {FAILURE_PATH}")

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
