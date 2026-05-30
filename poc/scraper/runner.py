import os
import subprocess
import time

URL = os.environ.get("SCRAPER_URL", "http://mock_site")
INTERVAL = int(os.environ.get("SCRAPE_INTERVAL", "10"))
SCRAPER_PATH = "/workspace/scraper.py"


def main():
    print(f"[runner] start: interval={INTERVAL}s url={URL}", flush=True)
    while True:
        if not os.path.exists(SCRAPER_PATH):
            print(f"[runner] {SCRAPER_PATH} not found, waiting...", flush=True)
            time.sleep(INTERVAL)
            continue

        proc = subprocess.run(
            ["python", SCRAPER_PATH, URL],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            print(f"[runner] OK  {proc.stdout.strip()}", flush=True)
        else:
            err = (proc.stderr or proc.stdout).strip().splitlines()
            print(f"[runner] FAIL {err[-1] if err else '(no output)'}", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
