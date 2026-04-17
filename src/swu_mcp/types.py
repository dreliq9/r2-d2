"""Typed inputs and outputs for r2-d2 tools.

Pydantic models for the search/lookup tool surface. The agent sees
SearchFilters as a constrained schema (typed enums, numeric comparators)
instead of an opaque `dict[str, str]`. Returns become typed envelopes
the agent can read directly via `structuredContent`.

CardSummary/CardDetail use a forgiving `model_validator(mode="before")`
so they accept both `CardRecord.to_summary()` (used by search) and
`CardRecord.to_dict()` (used by lookup) without changing the service layer.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# SWU domain enums
# ---------------------------------------------------------------------------

Aspect = Literal["Aggression", "Command", "Cunning", "Heroism", "Vigilance", "Villainy"]
CardType = Literal["Leader", "Base", "Unit", "Event", "Upgrade", "Token"]
Arena = Literal["Ground", "Space"]
Rarity = Literal["Common", "Uncommon", "Rare", "Legendary", "Special"]

# Set codes mirror card_service.CATALOG_SET_CODES
SetCode = Literal["SOR", "SHD", "TWI", "JTL", "LOF", "IBH", "SOP", "LAW"]

SearchOrder = Literal["name", "setnumber", "cost", "power", "hp", "rarity", "set"]
SortDirection = Literal["asc", "desc"]


# ---------------------------------------------------------------------------
# Numeric range filter — replaces magic strings like ">=3"
# ---------------------------------------------------------------------------

class NumericFilter(BaseModel):
    """Compare a numeric stat against a value.

    Renders to SWU-DB query syntax: `c>=3`, `p=4`, `h<5`, etc.
    """

    op: Literal["=", "!=", ">", ">=", "<", "<="] = Field(
        default="=",
        description="Comparison operator",
    )
    value: int = Field(ge=0, le=99, description="Stat value to compare against")

    def render(self, prefix: Literal["c", "p", "h"]) -> str:
        return f"{prefix}{self.op}{self.value}"


# ---------------------------------------------------------------------------
# Filters — replaces `filters: dict[str, str] | None`
# ---------------------------------------------------------------------------

class SearchFilters(BaseModel):
    """Structured filters for swu_search_cards.

    Each field maps to one SWU-DB query clause. Omitted fields are no-ops.
    Free-text matching belongs on the tool's `query` arg, not here.
    """

    model_config = ConfigDict(extra="forbid")  # typos like "asppect" raise ValidationError

    aspect: Optional[Aspect] = Field(default=None, description="Card aspect")
    type: Optional[CardType] = Field(default=None, description="Card type")
    arena: Optional[Arena] = Field(default=None, description="Where the card lives in play")
    rarity: Optional[Rarity] = Field(default=None, description="Card rarity")
    set: Optional[SetCode] = Field(default=None, description="Set code")
    trait: Optional[str] = Field(default=None, description='Trait keyword, e.g. "Bounty Hunter"')
    text: Optional[str] = Field(default=None, description="Substring to match in card text")

    cost: Optional[NumericFilter] = Field(default=None, description="Cost comparator")
    power: Optional[NumericFilter] = Field(default=None, description="Power comparator")
    hp: Optional[NumericFilter] = Field(default=None, description="HP comparator")

    def to_legacy_dict(self) -> dict[str, str]:
        """Render to the dict shape expected by card_service.compile_query.

        Lets us refactor the tool surface without touching the service layer.
        Numeric filters are rendered as SWU-DB strings (e.g. ">=3"); compile_query
        already handles those.
        """
        out: dict[str, str] = {}
        if self.aspect:
            out["aspect"] = self.aspect
        if self.type:
            out["type"] = self.type
        if self.arena:
            out["arena"] = self.arena
        if self.rarity:
            out["rarity"] = self.rarity
        if self.set:
            out["set"] = self.set
        if self.trait:
            out["trait"] = self.trait
        if self.text:
            out["text"] = self.text
        if self.cost:
            out["cost"] = f"{self.cost.op}{self.cost.value}"
        if self.power:
            out["power"] = f"{self.power.op}{self.power.value}"
        if self.hp:
            out["hp"] = f"{self.hp.op}{self.hp.value}"
        return out


# ---------------------------------------------------------------------------
# Card output shapes
# ---------------------------------------------------------------------------

class CardSummary(BaseModel):
    """Lightweight card view returned in search results.

    Accepts either CardRecord.to_summary() output (search path) or
    CardRecord.to_dict() output (lookup path) — synthesizes any missing
    aliases via _normalize so callers don't need a custom mapper.
    """

    id: str = Field(description="Stable lookup id, e.g. 'SOR/123'")
    lookup_id: str = Field(description="Same as id; kept for back-compat")
    set_code: str
    number: str
    name: str = Field(description="Display name including subtitle if present")
    display_name: str
    type: str
    card_type: str
    cost: Optional[str] = None
    power: Optional[str] = None
    hp: Optional[str] = None
    aspects: list[str] = Field(default_factory=list)
    traits: list[str] = Field(default_factory=list)
    arenas: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    rarity: Optional[str] = None
    front_text: Optional[str] = None
    epic_action: Optional[str] = None
    image_url: Optional[str] = None
    front_art: Optional[str] = None
    back_art: Optional[str] = None
    source: str = "api"

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        # Synthesize aliases so to_dict() output (lookup path) parses cleanly
        d.setdefault("lookup_id", d.get("id"))
        d.setdefault("id", d.get("lookup_id"))
        d.setdefault("display_name", d.get("name"))
        # Prefer display_name as `name` when both exist
        if d.get("display_name"):
            d["name"] = d["display_name"]
        d.setdefault("type", d.get("card_type"))
        d.setdefault("card_type", d.get("type"))
        d.setdefault("image_url", d.get("front_art"))
        return d


class CardDetail(CardSummary):
    """Full card record returned by swu_lookup_card."""

    subtitle: Optional[str] = None
    back_text: Optional[str] = None
    unique: bool = False
    double_sided: bool = False
    artist: Optional[str] = None
    variant_type: Optional[str] = None
    market_price: Optional[str] = None
    foil_price: Optional[str] = None


class SearchResult(BaseModel):
    """Top-level search result envelope."""

    query: str = Field(description="Compiled SWU-DB query string actually sent")
    returned_count: int
    total_matches: int
    source: Literal["api", "local-fallback"] = "api"
    warning: Optional[str] = Field(
        default=None,
        description="Set when the API failed and we fell back to local",
    )
    cards: list[CardSummary]

    def __str__(self) -> str:
        s = (
            f"{self.returned_count} of {self.total_matches} cards "
            f"(query: '{self.query}', source: {self.source})"
        )
        if self.warning:
            s += f" [WARN: {self.warning}]"
        return s
