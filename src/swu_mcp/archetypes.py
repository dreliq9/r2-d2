from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .card_identity import canonical_key


@dataclass(frozen=True)
class KnownArchetype:
    archetype_id: str
    format_name: str
    leader_keys: tuple[tuple[str, str], ...]
    name: str
    description: str
    signature_cards: tuple[str, ...]
    role_targets: dict[str, int]
    package_targets: tuple[str, ...]
    source_notes: tuple[str, ...]
    last_reviewed: str


ARCHETYPES: tuple[KnownArchetype, ...] = (
    KnownArchetype(
        archetype_id="twin-suns-kylo-trench-upgrades",
        format_name="twin_suns",
        leader_keys=(("kylo ren", "we're not done yet"), ("admiral trench", "chk-chk-chk-chk")),
        name="Kylo Ren / Admiral Trench Upgrade Recursion",
        description="Discard upgrades early, then recur them onto Kylo after deploy while Trench fuels discard and card flow.",
        signature_cards=("Snapshot Reflexes", "Sith Holocron", "Kylo's TIE Silencer", "Drain Essence"),
        role_targets={"upgrade": 18, "upgrade_carrier": 16, "removal": 10},
        package_targets=("discard_engine",),
        source_notes=("Local hand-built Kylo/Trench decklist and review notes.",),
        last_reviewed="2026-07-12",
    ),
)


def known_archetypes() -> list[KnownArchetype]:
    return list(ARCHETYPES)


def match_archetype(leaders: list[dict[str, Any]], format_name: str) -> KnownArchetype | None:
    leader_pairs = {
        (canonical_key(leader).name, canonical_key(leader).subtitle)
        for leader in leaders
    }
    for archetype in ARCHETYPES:
        if archetype.format_name != format_name:
            continue
        if set(archetype.leader_keys) <= leader_pairs:
            return archetype
    return None
