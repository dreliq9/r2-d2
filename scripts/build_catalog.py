from __future__ import annotations

import json
from pathlib import Path

import httpx

API_BASE_URL = "https://api.swu-db.com"

# SWU DB has renamed some OP promo set codes over time. Keep the live set code
# in the catalog, and also add alias records so older collection exports still
# resolve metadata.
SET_ALIASES = {
    "JTLP": "JTLOP",
    "LOFP": "LOFOP",
    "LAWP": "LAWOP",
}
TOKEN_ALIAS_SOURCE_SET = "TSOR"
TOKEN_ALIAS_SET = "TOKENS"


def fetch_set_codes(client: httpx.Client) -> list[str]:
    response = client.get("/sets")
    response.raise_for_status()
    payload = response.json()
    return sorted(
        {
            str(row.get("setId", "")).upper()
            for row in payload
            if row.get("setId")
        }
    )


def fetch_set_cards(client: httpx.Client, set_code: str) -> list[dict]:
    response = client.get(f"/cards/{set_code.lower()}", params={"pretty": "false"})
    response.raise_for_status()
    payload = response.json()
    return payload.get("data", [])


def alias_cards(cards_by_set: dict[str, list[dict]]) -> list[dict]:
    aliases: list[dict] = []
    for alias, canonical in SET_ALIASES.items():
        for card in cards_by_set.get(canonical, []):
            clone = dict(card)
            clone["Set"] = alias
            aliases.append(clone)
    for card in cards_by_set.get(TOKEN_ALIAS_SOURCE_SET, []):
        number = str(card.get("Number", "")).upper()
        if not (number.startswith("T") and number[1:].isdigit()):
            continue
        clone = dict(card)
        clone["Set"] = TOKEN_ALIAS_SET
        clone["Number"] = str(int(number[1:]))
        aliases.append(clone)
    return aliases


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    output_path = repo_root / "data" / "catalog" / "cards.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    catalog: list[dict] = []
    cards_by_set: dict[str, list[dict]] = {}
    with httpx.Client(base_url=API_BASE_URL, timeout=30.0) as client:
        for set_code in fetch_set_codes(client):
            print(f"Fetching {set_code}...")
            try:
                cards = fetch_set_cards(client, set_code)
            except httpx.HTTPError as error:
                print(f"  skipping {set_code}: {error}")
                continue
            cards_by_set[set_code] = cards
            catalog.extend(cards)

    alias_records = alias_cards(cards_by_set)
    if alias_records:
        print(f"Adding {len(alias_records)} compatibility alias records...")
        catalog.extend(alias_records)

    output_path.write_text(json.dumps({"cards": catalog}, indent=2), encoding="utf-8")
    print(f"Wrote {len(catalog)} cards to {output_path}")


if __name__ == "__main__":
    main()
