from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import httpx

from .catalog import LocalCatalog
from .config import settings
from .models import CardRecord


FIELD_ALIASES = {
    "aspect": "aspect",
    "aspects": "aspect",
    "trait": "trait",
    "traits": "trait",
    "type": "type",
    "card_type": "type",
    "arena": "arena",
    "rarity": "rarity",
    "cost": "cost",
    "power": "power",
    "hp": "hp",
    "set": "set",
    "text": "text",
}

CATALOG_SET_CODES = [
    "SOR",
    "SHD",
    "TWI",
    "JTL",
    "LOF",
    "IBH",
    "SOP",
    "LAW",
]


class CardService:
    def __init__(self) -> None:
        self.client = httpx.Client(base_url=settings.api_base_url, timeout=20.0)
        self.catalog = LocalCatalog(settings.card_catalog_path)
        self.cache_dir = settings.cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def search_cards(
        self,
        query: str,
        filters: dict[str, str] | None = None,
        *,
        limit: int | None = None,
        order: str = "name",
        direction: str = "asc",
    ) -> dict[str, Any]:
        resolved_limit = max(1, min(limit or settings.default_limit, 100))
        compiled_query = compile_query(query, filters)

        try:
            response = self.client.get(
                "/cards/search",
                params={
                    "q": compiled_query,
                    "order": order,
                    "dir": direction,
                },
            )
            response.raise_for_status()
            payload = response.json()
            cards = [CardRecord.from_api(card, source="api") for card in payload.get("data", [])[:resolved_limit]]
            self._write_cache("last-search.json", payload)
            return {
                "query": compiled_query,
                "returned_count": len(cards),
                "total_matches": payload.get("total_cards", len(cards)),
                "source": "api",
                "cards": [card.to_summary() for card in cards],
            }
        except httpx.HTTPError as error:
            self._ensure_local_catalog()
            cards = self.catalog.search(query, filters, resolved_limit)
            if cards:
                return {
                    "query": compiled_query,
                    "returned_count": len(cards),
                    "total_matches": len(cards),
                    "source": "local-fallback",
                    "warning": f"Live API unavailable: {error}",
                    "cards": [card.to_summary() for card in cards],
                }
            raise RuntimeError(f"SWU DB search failed and no local fallback matched '{compiled_query}'.") from error

    def lookup_card(
        self,
        *,
        name: str | None = None,
        set_code: str | None = None,
        card_number: str | None = None,
    ) -> dict[str, Any]:
        if set_code and card_number:
            return self._lookup_by_id(set_code=set_code, card_number=card_number)
        if name:
            return self._lookup_by_name(name)
        raise ValueError("Provide either a card name or both set_code and card_number.")

    def random_card(
        self,
        query: str = "",
        filters: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        result = self.search_cards(query=query or "*", filters=filters, limit=50, order="setnumber")
        cards = result.get("cards", [])
        if not cards:
            raise ValueError("No cards matched the supplied query.")
        chosen = random.choice(cards)
        return {
            "query": result["query"],
            "source": result["source"],
            "card": chosen,
        }

    def get_image(
        self,
        *,
        name: str | None = None,
        set_code: str | None = None,
        card_number: str | None = None,
        back_face: bool = False,
    ) -> dict[str, Any]:
        lookup = self.lookup_card(name=name, set_code=set_code, card_number=card_number)
        image_url = lookup.get("back_art") if back_face else lookup.get("front_art")
        if not image_url:
            raise ValueError("No image is available for the requested face.")
        return {
            "card": lookup.get("display_name"),
            "lookup_id": lookup.get("lookup_id"),
            "image_url": image_url,
            "face": "back" if back_face else "front",
            "source": lookup.get("source", "api"),
        }

    def _lookup_by_id(self, *, set_code: str, card_number: str) -> dict[str, Any]:
        normalized_set = set_code.strip().upper()
        normalized_number = normalize_lookup_number(card_number)
        try:
            response = self.client.get(f"/cards/{normalized_set.lower()}/{normalized_number}")
            response.raise_for_status()
            card = CardRecord.from_api(response.json(), source="api")
            self._write_cache(f"{card.lookup_id.replace('/', '-')}.json", card.raw)
            return card.to_dict()
        except httpx.HTTPError as error:
            self._ensure_local_catalog()
            card = self.catalog.lookup(normalized_set, normalized_number)
            if card:
                return card.to_dict()
            raise RuntimeError(
                f"SWU DB lookup failed for {normalized_set}/{normalized_number} and no local fallback card exists."
            ) from error

    def _lookup_by_name(self, name: str) -> dict[str, Any]:
        result = self.search_cards(name, limit=10, order="name")
        candidates = result["cards"]
        lowered_name = name.strip().lower()

        exact_match = next((card for card in candidates if card["name"].lower() == lowered_name), None)
        if exact_match:
            set_code, card_number = exact_match["id"].split("/", maxsplit=1)
            return self._lookup_by_id(set_code=set_code, card_number=card_number)

        prefix_match = next((card for card in candidates if card["name"].lower().startswith(lowered_name)), None)
        if prefix_match:
            set_code, card_number = prefix_match["id"].split("/", maxsplit=1)
            return self._lookup_by_id(set_code=set_code, card_number=card_number)

        raise ValueError(f"No card matched the supplied name: {name}")

    def _write_cache(self, filename: str, payload: dict[str, Any]) -> None:
        cache_path = self.cache_dir / filename
        cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _ensure_local_catalog(self) -> None:
        """Load an existing local catalog if available. Does NOT build from API."""
        if self.catalog.is_available():
            return
        if not self.catalog.catalog_path:
            return
        if self.catalog.catalog_path.exists():
            self.catalog = LocalCatalog(str(self.catalog.catalog_path))


def compile_query(query: str, filters: dict[str, str] | None) -> str:
    pieces: list[str] = []
    cleaned_query = query.strip()
    if cleaned_query and cleaned_query != "*":
        pieces.append(cleaned_query)

    for key, raw_value in (filters or {}).items():
        if raw_value is None:
            continue
        value = str(raw_value).strip()
        if not value:
            continue
        normalized_key = FIELD_ALIASES.get(key.lower())
        if not normalized_key:
            pieces.append(value)
            continue
        pieces.append(render_filter_clause(normalized_key, value))

    return " ".join(pieces) if pieces else "*"


def render_filter_clause(key: str, value: str) -> str:
    if key == "aspect":
        return f"aspect:{quote_if_needed(value)}"
    if key == "trait":
        return f"trait:{quote_if_needed(value)}"
    if key == "type":
        return f"type:{quote_if_needed(value)}"
    if key == "arena":
        return f"arena:{quote_if_needed(value)}"
    if key == "rarity":
        return f"rarity:{quote_if_needed(value)}"
    if key == "set":
        return f"set:{quote_if_needed(value)}"
    if key == "text":
        return f"text:{quote_if_needed(value)}"
    if key in {"cost", "power", "hp"}:
        prefix = {"cost": "c", "power": "p", "hp": "h"}[key]
        if value.startswith((">=", "<=", "!=", ">", "<", "=")):
            return f"{prefix}{value}"
        return f"{prefix}={value}"
    return value


def quote_if_needed(value: str) -> str:
    return f"\"{value}\"" if " " in value else value


def normalize_lookup_number(card_number: str) -> str:
    cleaned = str(card_number).strip().upper()
    digits = "".join(character for character in cleaned if character.isdigit())
    suffix = cleaned[len(digits):] if cleaned.startswith(digits) else ""
    if digits:
        return f"{int(digits):03d}{suffix}"
    return cleaned
