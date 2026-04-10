from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .models import CardRecord


class LocalCatalog:
    def __init__(self, catalog_path: str | None = None) -> None:
        self.catalog_path = Path(catalog_path) if catalog_path else None
        self._cards: list[CardRecord] | None = None

    def is_available(self) -> bool:
        return bool(self.catalog_path and self.catalog_path.exists())

    def all_cards(self) -> list[CardRecord]:
        if self._cards is not None:
            return self._cards

        if not self.is_available():
            self._cards = []
            return self._cards

        payload = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            raw_cards = payload.get("cards", payload.get("data", []))
        elif isinstance(payload, list):
            raw_cards = payload
        else:
            raw_cards = []

        self._cards = [CardRecord.from_api(card, source="local") for card in raw_cards]
        return self._cards

    def lookup(self, set_code: str, card_number: str) -> CardRecord | None:
        normalized_set = set_code.strip().upper()
        normalized_number = normalize_card_number(card_number)
        for card in self.all_cards():
            if card.set_code == normalized_set and normalize_card_number(card.number) == normalized_number:
                return card
        return None

    def lookup_by_name(
        self,
        name: str,
        *,
        preferred_type: str | None = None,
        exclude_types: set[str] | None = None,
    ) -> CardRecord | None:
        lowered_name = name.strip().lower()
        cards = self.all_cards()
        if exclude_types:
            cards = [card for card in cards if card.card_type not in exclude_types]

        exact_display = [card for card in cards if card.display_name.lower() == lowered_name]
        exact_title = [card for card in cards if card.name.lower() == lowered_name]
        prefix_matches = [card for card in cards if card.display_name.lower().startswith(lowered_name)]

        for candidates in (exact_display, exact_title, prefix_matches):
            if preferred_type:
                typed_match = next((card for card in candidates if card.card_type == preferred_type), None)
                if typed_match:
                    return typed_match
            if candidates:
                return candidates[0]
        return None

    def search(self, query: str, filters: dict[str, str] | None = None, limit: int = 10) -> list[CardRecord]:
        query_terms = tokenize(query)
        filters = {key.lower(): value for key, value in (filters or {}).items() if value}
        matches: list[CardRecord] = []
        for card in self.all_cards():
            if not matches_query(card, query_terms):
                continue
            if not matches_filters(card, filters):
                continue
            matches.append(card)
            if len(matches) >= limit:
                break
        return matches


def normalize_card_number(card_number: str) -> str:
    normalized = str(card_number).strip().upper()
    digits = "".join(character for character in normalized if character.isdigit())
    suffix = normalized[len(digits):] if normalized.startswith(digits) else normalized.lstrip("0")
    if digits:
        return f"{int(digits):03d}{suffix}"
    return normalized


def tokenize(query: str) -> list[str]:
    return [term.lower() for term in query.split() if term.strip()]


def matches_query(card: CardRecord, query_terms: Iterable[str]) -> bool:
    haystack = " ".join(
        [
            card.name,
            card.subtitle or "",
            card.card_type,
            " ".join(card.aspects),
            " ".join(card.traits),
            " ".join(card.arenas),
            " ".join(card.keywords),
            card.front_text or "",
            card.back_text or "",
            card.epic_action or "",
        ]
    ).lower()
    return all(term in haystack for term in query_terms)


def matches_filters(card: CardRecord, filters: dict[str, str]) -> bool:
    for key, value in filters.items():
        expected = value.lower()
        if key == "aspect" and expected not in [aspect.lower() for aspect in card.aspects]:
            return False
        if key == "trait" and expected not in [trait.lower() for trait in card.traits]:
            return False
        if key == "type" and expected != card.card_type.lower():
            return False
        if key == "arena" and expected not in [arena.lower() for arena in card.arenas]:
            return False
        if key == "rarity" and expected != (card.rarity or "").lower():
            return False
        if key == "set" and expected != card.set_code.lower():
            return False
        if key == "cost" and expected != (card.cost or "").lower():
            return False
    return True
