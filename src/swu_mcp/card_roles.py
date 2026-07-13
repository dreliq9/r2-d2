from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .deck_service import parse_int
from .deck_thesis import DeckThesis


@dataclass(frozen=True)
class CardRoleProfile:
    roles: tuple[str, ...]
    score_by_role: dict[str, float] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()


def _text(card: dict[str, Any]) -> str:
    return " ".join(
        str(card.get(key) or "")
        for key in ("front_text", "FrontText", "epic_action", "EpicAction", "back_text", "BackText")
    ).lower()


def roles_for_card(card: dict[str, Any], thesis: DeckThesis) -> CardRoleProfile:
    roles: set[str] = set()
    scores: dict[str, float] = {}
    reasons: list[str] = []
    ctype = str(card.get("card_type") or card.get("Type") or "")
    cost = parse_int(card.get("cost") if card.get("cost") is not None else card.get("Cost"))
    text = _text(card)
    keywords = set(card.get("keywords") or card.get("Keywords") or [])
    arenas = set(card.get("arenas") or card.get("Arenas") or [])
    hp = parse_int(card.get("hp") or card.get("HP")) or 0
    power = parse_int(card.get("power") or card.get("Power")) or 0

    def add(role: str, score: float, reason: str) -> None:
        roles.add(role)
        scores[role] = max(scores.get(role, 0.0), score)
        reasons.append(reason)

    # Preserve the analysis-facing role vocabulary while adding the more
    # specific deckbuilding roles below.
    if any(token in text for token in ("defeat", "deal", "damage to a unit", "capture")):
        add("removal", 6.0, "interactive text")
    if any(token in text for token in ("damage to a base", "enemy base", "opponent's base")):
        add("base_pressure", 4.0, "base pressure text")
    if any(token in text for token in ("draw", "search the top", "look at the top", "ready")):
        add("card_advantage", 5.0, "card selection or draw")
    if any(token in text for token in ("restore", "shield", "sentinel", "heal")):
        add("defense", 4.0, "defensive text")
    if any(token in text for token in ("return", "exhaust", "discard", "ready this unit")):
        add("tempo", 4.0, "tempo text")

    if ctype == "Unit":
        add("board_presence", 1.0, "unit card")
        if cost is not None and cost <= 2:
            add("early_unit", 6.0, "cheap unit")
        if cost is not None and cost >= 5:
            add("finisher", 4.0 + power, "top-end unit")
        if "Ground" in arenas and hp >= 3:
            add("upgrade_carrier", 4.0 + min(hp, 6), "durable ground body")
        if keywords & {"Sentinel", "Restore", "Shielded", "Grit"}:
            add("defensive_stabilizer", 4.0, "defensive keyword")
        if "When Played:" in str(card.get("front_text") or card.get("FrontText") or ""):
            add("engine_payoff", 3.0, "when-played trigger")
    if ctype == "Upgrade":
        add("upgrade", 8.0, "upgrade card")
        if "from your discard pile" in text:
            add("engine_payoff", 6.0, "discard recursion payoff")
    if any(package in thesis.target_packages for package in ("discard_engine", "replay_engine", "pilot_vehicle", "bounty_hunter")):
        if any(token in text for token in ("discard a card", "play a card from your discard", "piloting", "bounty")):
            add("engine_enabler", 5.0, "matches target package text")

    return CardRoleProfile(
        roles=tuple(sorted(roles)),
        score_by_role=scores,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def build_role_pools(cards: list[dict[str, Any]], thesis: DeckThesis) -> dict[str, list[dict[str, Any]]]:
    pools: dict[str, list[dict[str, Any]]] = {role: [] for role in thesis.role_targets}
    for card in cards:
        profile = roles_for_card(card, thesis)
        enriched = {**card, "_role_profile": profile}
        for role in profile.roles:
            pools.setdefault(role, []).append(enriched)
    for role, pool in pools.items():
        pool.sort(key=lambda card: card["_role_profile"].score_by_role.get(role, 0.0), reverse=True)
    return pools
