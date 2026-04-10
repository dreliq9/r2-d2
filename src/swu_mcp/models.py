from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class CardRecord:
    set_code: str
    number: str
    name: str
    subtitle: str | None
    card_type: str
    aspects: list[str] = field(default_factory=list)
    traits: list[str] = field(default_factory=list)
    arenas: list[str] = field(default_factory=list)
    cost: str | None = None
    power: str | None = None
    hp: str | None = None
    keywords: list[str] = field(default_factory=list)
    front_text: str | None = None
    epic_action: str | None = None
    back_text: str | None = None
    front_art: str | None = None
    back_art: str | None = None
    rarity: str | None = None
    unique: bool = False
    double_sided: bool = False
    artist: str | None = None
    variant_type: str | None = None
    market_price: str | None = None
    foil_price: str | None = None
    source: str = "api"
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict[str, Any], *, source: str = "api") -> "CardRecord":
        return cls(
            set_code=str(payload.get("Set", "")).upper(),
            number=str(payload.get("Number", "")).upper(),
            name=str(payload.get("Name", "")),
            subtitle=payload.get("Subtitle"),
            card_type=str(payload.get("Type", "")),
            aspects=list(payload.get("Aspects", []) or []),
            traits=list(payload.get("Traits", []) or []),
            arenas=list(payload.get("Arenas", []) or []),
            cost=string_or_none(payload.get("Cost")),
            power=string_or_none(payload.get("Power")),
            hp=string_or_none(payload.get("HP")),
            keywords=list(payload.get("Keywords", []) or []),
            front_text=payload.get("FrontText"),
            epic_action=payload.get("EpicAction"),
            back_text=payload.get("BackText"),
            front_art=payload.get("FrontArt"),
            back_art=payload.get("BackArt"),
            rarity=payload.get("Rarity"),
            unique=bool(payload.get("Unique", False)),
            double_sided=bool(payload.get("DoubleSided", False)),
            artist=payload.get("Artist"),
            variant_type=payload.get("VariantType"),
            market_price=string_or_none(payload.get("MarketPrice")),
            foil_price=string_or_none(payload.get("FoilPrice")),
            source=source,
            raw=payload,
        )

    @property
    def display_name(self) -> str:
        return f"{self.name} - {self.subtitle}" if self.subtitle else self.name

    @property
    def lookup_id(self) -> str:
        return f"{self.set_code}/{self.number}"

    def to_summary(self) -> dict[str, Any]:
        return {
            "id": self.lookup_id,
            "lookup_id": self.lookup_id,
            "set_code": self.set_code,
            "number": self.number,
            "name": self.display_name,
            "display_name": self.display_name,
            "type": self.card_type,
            "card_type": self.card_type,
            "cost": self.cost,
            "power": self.power,
            "hp": self.hp,
            "aspects": self.aspects,
            "traits": self.traits,
            "arenas": self.arenas,
            "keywords": self.keywords,
            "rarity": self.rarity,
            "front_text": self.front_text,
            "epic_action": self.epic_action,
            "image_url": self.front_art,
            "front_art": self.front_art,
            "back_art": self.back_art,
            "source": self.source,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "display_name": self.display_name,
            "lookup_id": self.lookup_id,
        }


def string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
