"""Build collection_enriched.json from collection.json + per-card cache.

Fetches any missing cards from api.swu-db.com in parallel, caches them in
.swu-mcp-cache/ in the same format the MCP uses, then writes an enriched
collection file with Name/Type/Rarity/Keywords merged onto each entry.
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / ".swu-mcp-cache"
COLLECTION = CACHE_DIR / "collection.json"
ENRICHED = CACHE_DIR / "collection_enriched.json"

API = "https://api.swu-db.com/cards/{set_code}/{number}"


def pad_num(n: str | int) -> str:
    return str(n).zfill(3)


def cache_path(set_code: str, number: str) -> Path:
    return CACHE_DIR / f"{set_code.upper()}-{pad_num(number)}.json"


def fetch_card(set_code: str, number: str) -> dict | None:
    url = API.format(set_code=set_code.lower(), number=str(number).lstrip("0") or "0")
    req = Request(url, headers={"User-Agent": "swu-mcp-enrich/1.0"})
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, json.JSONDecodeError) as e:
        print(f"  ! fetch failed {set_code}-{number}: {e}", file=sys.stderr)
        return None


def load_card(set_code: str, number: str) -> dict | None:
    p = cache_path(set_code, number)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    data = fetch_card(set_code, number)
    if data:
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def main() -> int:
    coll = json.loads(COLLECTION.read_text(encoding="utf-8"))
    entries = coll["entries"]
    print(f"Loaded {len(entries)} collection entries")

    missing = [
        (e["set_code"], e["card_number"])
        for e in entries
        if not cache_path(e["set_code"], e["card_number"]).exists()
    ]
    print(f"Cache hits: {len(entries) - len(missing)}, fetching {len(missing)}")

    if missing:
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = {
                ex.submit(load_card, sc, num): (sc, num) for sc, num in missing
            }
            for i, fut in enumerate(as_completed(futures), 1):
                sc, num = futures[fut]
                fut.result()
                if i % 25 == 0 or i == len(missing):
                    print(f"  fetched {i}/{len(missing)}")

    enriched = []
    failures = []
    for e in entries:
        card = load_card(e["set_code"], e["card_number"])
        if not card:
            failures.append((e["set_code"], e["card_number"]))
            enriched.append({**e, "lookup_failed": True})
            continue
        enriched.append(
            {
                **e,
                "name": card.get("Name"),
                "subtitle": card.get("Subtitle"),
                "type": card.get("Type"),
                "rarity": card.get("Rarity"),
                "keywords": card.get("Keywords", []),
                "aspects": card.get("Aspects", []),
                "traits": card.get("Traits", []),
            }
        )

    ENRICHED.write_text(
        json.dumps({"entries": enriched}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Wrote {ENRICHED} ({len(enriched)} entries, {len(failures)} failures)")
    if failures:
        print("Failures:", failures[:20])
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
