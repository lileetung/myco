import json
import sys
import traceback
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

URL = sys.argv[1] if len(sys.argv) > 1 else "http://mock_site"
FAILURE_PATH = Path(__file__).resolve().parent / "failure.json"


def main():
    html = None
    try:
        resp = httpx.get(URL, timeout=10.0)
        resp.raise_for_status()
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")

        title = soup.select_one("h1.product-title").get_text(strip=True)
        price = soup.select_one(".price").get_text(strip=True)
        sku = soup.select_one(".sku").get_text(strip=True).replace("SKU: ", "")
        description = soup.select_one(".description").get_text(strip=True)

        result = {
            "title": title,
            "price": price,
            "sku": sku,
            "description": description,
        }
        missing = [k for k, v in result.items() if v is None or v == ""]
        if missing:
            raise ValueError(f"Required fields missing or empty: {missing}")
        print(json.dumps(result))
        FAILURE_PATH.unlink(missing_ok=True)
    except Exception as e:
        failure = {
            "error_class": type(e).__name__,
            "error_message": str(e),
            "trace": traceback.format_exc(),
            "url": URL,
            "html": html,
        }
        FAILURE_PATH.write_text(json.dumps(failure, indent=2))
        print(f"SCRAPE FAILED: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
