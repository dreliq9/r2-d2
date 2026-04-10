from __future__ import annotations

import json
from pathlib import Path

import httpx

API_BASE_URL = "https://api.swu-db.com"
DEFAULT_SETS = [
    "SOR",
    "SHD",
    "TWI",
    "JTL",
    "LOF",
    "IBH",
    "SOP",
    "LAW",
]


def fetch_set_cards(client: httpx.Client, set_code: str) -> list[dict]:
    response = client.get(f"/cards/{set_code.lower()}", params={"pretty": "false"})
    response.raise_for_status()
    payload = response.json()
    return payload.get("data", [])


def main() -> None:
    output_path = Path("data/catalog/cards.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    catalog: list[dict] = []
    with httpx.Client(base_url=API_BASE_URL, timeout=30.0) as client:
        for set_code in DEFAULT_SETS:
            print(f"Fetching {set_code}...")
            catalog.extend(fetch_set_cards(client, set_code))

    output_path.write_text(json.dumps({"cards": catalog}, indent=2), encoding="utf-8")
    print(f"Wrote {len(catalog)} cards to {output_path}")


if __name__ == "__main__":
    main()

