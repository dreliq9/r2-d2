from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class CanonicalCardKey:
    name: str
    subtitle: str
    card_type: str


@dataclass(frozen=True)
class OwnedPrinting:
    set_code: str
    card_number: str
    count: int
    foil_count: int
    canonical_key: CanonicalCardKey


def _clean(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _card_type(card: dict) -> str:
    return str(card.get("card_type") or card.get("Type") or card.get("type") or "").strip()


def canonical_key(card: dict) -> CanonicalCardKey:
    name = _clean(card.get("name") or card.get("Name") or card.get("display_name") or "")
    subtitle = _clean(card.get("subtitle") or card.get("Subtitle") or "")
    if " - " in name and not subtitle:
        title, subtitle_from_display = name.split(" - ", 1)
        name = title.strip()
        subtitle = subtitle_from_display.strip()
    return CanonicalCardKey(
        name=name,
        subtitle=subtitle,
        card_type=_card_type(card),
    )
