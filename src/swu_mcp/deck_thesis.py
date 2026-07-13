from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from .archetypes import match_archetype


# Theme keyword → combo package(s) it implies. Shared by thesis construction
# and leader-pair ranking so both use the same package vocabulary.
THEME_TO_PACKAGES: dict[str, set[str]] = {
    "force": {"force_engine"},
    "jedi": {"force_engine"},
    "lightsaber": {"force_engine"},
    "indirect": {"indirect_damage"},
    "bounty": {"bounty_hunter", "indirect_damage"},
    "hunter": {"bounty_hunter"},
    "defeat": {"when_defeated"},
    "sacrifice": {"when_defeated"},
    "exploit": {"when_defeated"},
    "death": {"when_defeated"},
    "pilot": {"pilot_vehicle"},
    "vehicle": {"pilot_vehicle"},
    "fighter": {"pilot_vehicle"},
    "token": {"token_swarm"},
    "swarm": {"token_swarm"},
    "wide": {"token_swarm"},
    "ramp": {"cost_reduction"},
    "discount": {"cost_reduction"},
    "cheap": {"cost_reduction"},
    "sentinel": {"fortress"},
    "defense": {"fortress"},
    "defensive": {"fortress"},
    "wall": {"fortress"},
    "fortress": {"fortress"},
    "control": {"fortress"},
    "exhaust": {"exhaust_engine"},
    "ready": {"exhaust_engine"},
    "tap": {"exhaust_engine"},
    "mandalorian": {"mandalorian"},
    "mando": {"mandalorian"},
    "bounce": {"replay_engine"},
    "replay": {"replay_engine"},
    "re-trigger": {"replay_engine"},
    "retrigger": {"replay_engine"},
    "when played": {"replay_engine"},
    "grit": {"self_damage_engine"},
    "self-damage": {"self_damage_engine"},
    "self damage": {"self_damage_engine"},
    "on attack": {"attack_engine"},
    "attack-engine": {"attack_engine"},
    "free attack": {"attack_engine"},
    "discard": {"discard_engine"},
    "graveyard": {"discard_engine"},
    "recursion": {"discard_engine"},
    "from discard": {"discard_engine"},
}


@dataclass(frozen=True)
class RoleTarget:
    minimum: int
    ideal: int
    maximum: int


@dataclass(frozen=True)
class DeckThesis:
    format_name: str
    leader_names: tuple[str, ...]
    base_name: str | None
    legal_aspects: tuple[str, ...]
    target_packages: tuple[str, ...]
    role_targets: dict[str, RoleTarget] = field(default_factory=dict)
    type_targets: dict[str, int] = field(default_factory=dict)
    curve_targets: dict[str, int] = field(default_factory=dict)
    arena_targets: dict[str, int] = field(default_factory=dict)
    must_include: tuple[str, ...] = ()
    avoid_packages: tuple[str, ...] = ()
    signature_cards: tuple[str, ...] = ()
    matchup_priorities: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def target_packages_for_theme(theme: str) -> set[str]:
    lowered = (theme or "").lower()
    out: set[str] = set()
    for token, packages in THEME_TO_PACKAGES.items():
        if token in lowered:
            out |= packages
    return out


def _leader_text(leaders: list[dict[str, Any]]) -> str:
    return " ".join(
        str(leader.get(key) or "")
        for leader in leaders
        for key in ("front_text", "FrontText", "back_text", "BackText", "epic_action", "EpicAction")
    ).lower()


def _target(minimum: int, ideal: int, maximum: int) -> RoleTarget:
    return RoleTarget(minimum=minimum, ideal=ideal, maximum=maximum)


def build_deck_thesis(
    theme: str,
    leaders: list[dict[str, Any]],
    base: dict[str, Any] | None,
    format_name: str,
    meta_context: dict[str, Any] | None = None,
) -> DeckThesis:
    text = f"{theme} {_leader_text(leaders)}".lower()
    packages = target_packages_for_theme(theme)
    if "upgrade" in text and ("discard" in text or "discard pile" in text):
        packages.add("discard_engine")
    role_targets: dict[str, RoleTarget] = {
        "early_unit": _target(10, 16, 24),
        "removal": _target(6, 10, 16),
        "card_advantage": _target(4, 8, 14),
        "engine_enabler": _target(4, 8, 16),
        "engine_payoff": _target(4, 8, 16),
        "defensive_stabilizer": _target(4, 8, 14),
        "finisher": _target(2, 5, 9),
        "upgrade": _target(3, 6, 10),
        "upgrade_carrier": _target(6, 10, 18),
    }
    type_targets = {"Unit": 62, "Event": 14, "Upgrade": 4}
    notes: list[str] = []
    if re.search(r"\bupgrades?\b", text):
        role_targets["upgrade"] = _target(14, 18, 24)
        role_targets["upgrade_carrier"] = _target(10, 16, 24)
        role_targets["defensive_stabilizer"] = _target(6, 10, 16)
        type_targets = {"Unit": 48, "Event": 14, "Upgrade": 18}
        notes.append("Upgrade engine detected from theme or leader text.")
    if "pilot_vehicle" in packages:
        role_targets["engine_enabler"] = _target(8, 14, 24)
        role_targets["engine_payoff"] = _target(6, 12, 20)
        notes.append("Vehicle/Pilot package intentionally active.")
    legal_aspects = {
        aspect
        for card in leaders + ([base] if base else [])
        for aspect in (card.get("aspects") or card.get("Aspects") or [])
    }
    archetype = match_archetype(leaders, format_name)
    signature_cards: tuple[str, ...] = ()
    if archetype is not None:
        packages |= set(archetype.package_targets)
        signature_cards = archetype.signature_cards
        for role, ideal in archetype.role_targets.items():
            current = role_targets.get(role)
            if current is not None:
                role_targets[role] = _target(current.minimum, max(current.ideal, ideal), current.maximum)
    return DeckThesis(
        format_name=format_name,
        leader_names=tuple(str(leader.get("display_name") or leader.get("Name") or "") for leader in leaders),
        base_name=str(base.get("display_name") or base.get("Name")) if base else None,
        legal_aspects=tuple(sorted(legal_aspects)),
        target_packages=tuple(sorted(packages)),
        role_targets=role_targets,
        type_targets=type_targets,
        curve_targets={"0-2": 24, "3-4": 18, "5+": 8},
        arena_targets={"Ground": 24, "Space": 16},
        signature_cards=signature_cards,
        matchup_priorities=tuple(str(item) for item in (meta_context or {}).get("priorities", [])),
        notes=tuple(notes),
    )
