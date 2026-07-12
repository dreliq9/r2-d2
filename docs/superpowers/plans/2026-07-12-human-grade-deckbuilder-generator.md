# Human-Grade Deckbuilder Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a collection-aware, thesis-driven, evaluator-backed SWU deckbuilder that can generate, optimize, test, and explain decks at or above strong human deckbuilding quality.

**Architecture:** Keep the existing `DeckService` MCP surface stable while extracting focused modules for identity, thesis generation, role tagging, evaluation, optimization, simulation reporting, and archetypes. The first-pass `swu_generate_deck` remains available; new optimized flows compose the new modules and return structured reports.

**Tech Stack:** Python 3.12+, FastMCP, Pydantic-style dict payloads already used by the server, local catalog JSON, pytest via `PYTHONPATH=src uv run pytest`.

## Global Constraints

- Normal generation must not require live network access.
- Existing MCP tools must remain stable unless a task explicitly adds a new tool.
- `only_owned=True` means leaders, base, and main deck resolve through owned canonical cards.
- Twin Suns generation must never return a successful one-leader deck.
- Unknown archetypes must still work through heuristic thesis and evaluator paths.
- Simulation reports must state when relevant mechanics are approximated by the current rules engine.
- Each task must be implemented test-first and committed independently.

---

## File Structure

- Create `src/swu_mcp/card_identity.py`: canonical card keys, owned-printing lookup, and identity utilities.
- Modify `src/swu_mcp/collection_service.py`: expose canonical ownership indexes.
- Modify `src/swu_mcp/deck_service.py`: use canonical resolution, thesis, role pools, evaluator, and optimizer entrypoints while preserving existing tools.
- Create `src/swu_mcp/deck_thesis.py`: `DeckThesis`, role target derivation, package/theme normalization.
- Create `src/swu_mcp/card_roles.py`: role detection and role-aware candidate pool generation.
- Create `src/swu_mcp/deck_evaluator.py`: structured `DeckEvaluation`, card diagnostics, scoring axes.
- Create `src/swu_mcp/deck_optimizer.py`: local swap loop and swap explanations.
- Create `src/swu_mcp/deck_testing.py`: goldfish, focused line tests, and gauntlet report helpers over `GameService`.
- Create `src/swu_mcp/archetypes.py`: curated archetype records and matching helpers.
- Modify `src/swu_mcp/server.py`: expose optimized generation, evaluation, optimization, gauntlet, slot explanation, and known archetype MCP tools.
- Add tests under `tests/` for every new module and modified public behavior.

---

### Task 1: Canonical Identity And Owned Printing Resolution

**Files:**
- Create: `src/swu_mcp/card_identity.py`
- Modify: `src/swu_mcp/collection_service.py`
- Test: `tests/test_card_identity.py`

**Interfaces:**
- Produces: `CanonicalCardKey`, `canonical_key(card: dict) -> CanonicalCardKey`, `OwnedPrinting`, `CollectionService.owned_canonical_index() -> dict[CanonicalCardKey, list[OwnedPrinting]]`, `CollectionService.owned_canonical_count(card: dict) -> int`, `CollectionService.choose_owned_printing(card: dict) -> OwnedPrinting | None`.
- Consumes: existing collection entries and local catalog/cache records.

- [ ] **Step 1: Write failing canonical identity tests**

Create `tests/test_card_identity.py`:

```python
from pathlib import Path

from swu_mcp.card_identity import CanonicalCardKey, canonical_key
from swu_mcp.collection_service import CollectionService


def test_canonical_key_collapses_same_named_printings() -> None:
    base = {
        "Name": "Qui-Gon Jinn",
        "Subtitle": "Student of the Living Force",
        "Type": "Leader",
    }
    variant = {
        "name": "Qui-Gon Jinn",
        "subtitle": "Student of the Living Force",
        "card_type": "Leader",
        "set_code": "G25",
        "number": "1",
    }

    assert canonical_key(base) == canonical_key(variant)
    assert canonical_key(base) == CanonicalCardKey(
        name="qui-gon jinn",
        subtitle="student of the living force",
        card_type="Leader",
    )


def test_collection_owned_canonical_index_counts_variants(tmp_path: Path) -> None:
    collection_path = tmp_path / "collection.json"
    collection_path.write_text(
        """
        {
          "entries": [
            {
              "set_code": "LOF",
              "card_number": "016",
              "count": 1,
              "foil_count": 0,
              "name": "Qui-Gon Jinn",
              "subtitle": "Student of the Living Force",
              "type": "Leader"
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    service = CollectionService(collection_path)
    requested = {
        "name": "Qui-Gon Jinn",
        "subtitle": "Student of the Living Force",
        "card_type": "Leader",
        "set_code": "G25",
        "number": "1",
    }

    assert service.owned_canonical_count(requested) == 1
    printing = service.choose_owned_printing(requested)
    assert printing is not None
    assert printing.set_code == "LOF"
    assert printing.card_number == "16"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
cd "/Users/adamsteen/projects/mcps/SWU-MCP codename Hyperspeed"
PYTHONPATH=src uv run pytest tests/test_card_identity.py -q
```

Expected: FAIL because `swu_mcp.card_identity` and canonical collection methods do not exist.

- [ ] **Step 3: Implement canonical identity module**

Create `src/swu_mcp/card_identity.py`:

```python
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
```

- [ ] **Step 4: Add canonical collection methods**

Modify `src/swu_mcp/collection_service.py` imports:

```python
from .card_identity import CanonicalCardKey, OwnedPrinting, canonical_key
```

Add methods inside `CollectionService`:

```python
    def owned_canonical_index(self) -> dict[CanonicalCardKey, list[OwnedPrinting]]:
        self._load_from_disk()
        index: dict[CanonicalCardKey, list[OwnedPrinting]] = {}
        for entry in self._entries.values():
            card = (
                _read_card_cache(entry.set_code, entry.card_number)
                or _read_card_catalog(entry.set_code, entry.card_number)
                or {
                    "Name": "",
                    "Subtitle": "",
                    "Type": "",
                    "name": "",
                    "subtitle": "",
                    "type": "",
                }
            )
            if not card.get("Name") and not card.get("name"):
                continue
            key = canonical_key(card)
            index.setdefault(key, []).append(
                OwnedPrinting(
                    set_code=entry.set_code,
                    card_number=entry.card_number,
                    count=entry.count,
                    foil_count=entry.foil_count,
                    canonical_key=key,
                )
            )
        return index

    def owned_canonical_count(self, card: dict) -> int:
        return sum(printing.count for printing in self.owned_canonical_index().get(canonical_key(card), []))

    def choose_owned_printing(self, card: dict) -> OwnedPrinting | None:
        printings = self.owned_canonical_index().get(canonical_key(card), [])
        if not printings:
            return None
        return sorted(printings, key=lambda p: (p.set_code, p.card_number))[0]
```

- [ ] **Step 5: Run tests to verify pass**

Run:

```bash
PYTHONPATH=src uv run pytest tests/test_card_identity.py -q
```

Expected: PASS.

- [ ] **Step 6: Run full test suite**

Run:

```bash
PYTHONPATH=src uv run pytest -q
```

Expected: all existing tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/swu_mcp/card_identity.py src/swu_mcp/collection_service.py tests/test_card_identity.py
git commit -m "feat: add canonical card identity"
```

---

### Task 2: Fail-Fast Leader And Base Resolution

**Files:**
- Modify: `src/swu_mcp/deck_service.py`
- Test: `tests/test_deck_generation_resolution.py`

**Interfaces:**
- Consumes: `CollectionService.choose_owned_printing(card: dict) -> OwnedPrinting | None`.
- Produces: `_resolve_requested_leaders(leader_names: list[str], format_name: str, only_owned: bool) -> list[dict[str, Any]]` and fail-fast generation errors.

- [ ] **Step 1: Write failing leader resolution tests**

Create `tests/test_deck_generation_resolution.py`:

```python
from pathlib import Path

import pytest

from swu_mcp.card_service import CardService
from swu_mcp.collection_service import CollectionService
from swu_mcp.deck_service import DeckService, TWIN_SUNS


def _collection(path: Path) -> CollectionService:
    path.write_text(
        """
        {
          "entries": [
            {
              "set_code": "LOF",
              "card_number": "016",
              "count": 1,
              "foil_count": 0,
              "name": "Qui-Gon Jinn",
              "subtitle": "Student of the Living Force",
              "type": "Leader"
            },
            {
              "set_code": "LOF",
              "card_number": "007",
              "count": 1,
              "foil_count": 0,
              "name": "Avar Kriss",
              "subtitle": "Marshal of Starlight",
              "type": "Leader"
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    return CollectionService(path)


def test_requested_twin_suns_leaders_resolve_by_owned_canonical_identity(tmp_path: Path) -> None:
    service = DeckService(CardService(), collection_service=_collection(tmp_path / "collection.json"))

    leaders = service._pick_leaders(
        theme="Force replay",
        format_name=TWIN_SUNS,
        leader_names=[
            "Qui-Gon Jinn - Student of the Living Force",
            "Avar Kriss - Marshal of Starlight",
        ],
        only_owned=True,
    )

    assert [leader["display_name"] for leader in leaders] == [
        "Qui-Gon Jinn - Student of the Living Force",
        "Avar Kriss - Marshal of Starlight",
    ]


def test_requested_twin_suns_missing_leader_fails_loudly(tmp_path: Path) -> None:
    service = DeckService(CardService(), collection_service=_collection(tmp_path / "collection.json"))

    with pytest.raises(ValueError, match="Could not resolve requested leader"):
        service.generate_deck(
            theme="Force replay",
            format_name=TWIN_SUNS,
            leader_names=["Missing Leader", "Avar Kriss - Marshal of Starlight"],
            only_owned=True,
        )
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=src uv run pytest tests/test_deck_generation_resolution.py -q
```

Expected: FAIL because requested leaders are not resolved through owned canonical identity and missing leaders are silently dropped.

- [ ] **Step 3: Implement requested leader resolver**

Modify `DeckService._pick_leaders` in `src/swu_mcp/deck_service.py`:

```python
        if leader_names:
            leaders = []
            unresolved: list[str] = []
            for name in leader_names:
                leader = self._resolve_leader_by_name(name)
                if leader is None:
                    unresolved.append(name)
                    continue
                if only_owned and self.collection_service is not None:
                    owned_printing = self.collection_service.choose_owned_printing(leader)
                    if owned_printing is None:
                        unresolved.append(name)
                        continue
                    owned_card = self.card_service.catalog.lookup(
                        owned_printing.set_code,
                        owned_printing.card_number,
                    )
                    if owned_card is not None:
                        leader = owned_card.to_dict()
                leaders.append(leader)
            if unresolved:
                raise ValueError(
                    "Could not resolve requested leader(s) as owned cards: "
                    + ", ".join(unresolved)
                )
```

After this block, add a Twin Suns guard before returning:

```python
        if format_name == TWIN_SUNS and leader_names and len(leaders) != TWIN_SUNS_LEADER_COUNT:
            raise ValueError(
                f"Twin Suns requires {TWIN_SUNS_LEADER_COUNT} requested leaders; resolved {len(leaders)}."
            )
```

- [ ] **Step 4: Add final generation legality guard**

After `validation = self.validate_parsed_deck(parsed)` in `generate_deck`, add:

```python
        if not validation["legal"]:
            raise ValueError(
                "Generated deck failed validation: "
                + "; ".join(validation.get("errors") or ["unknown validation error"])
            )
```

- [ ] **Step 5: Run tests**

Run:

```bash
PYTHONPATH=src uv run pytest tests/test_deck_generation_resolution.py -q
```

Expected: PASS.

- [ ] **Step 6: Regression test current focused suite**

Run:

```bash
PYTHONPATH=src uv run pytest tests/test_card_identity.py tests/test_combo_packages.py tests/test_deck_generation_scoring.py tests/test_deck_generation_resolution.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/swu_mcp/deck_service.py tests/test_deck_generation_resolution.py
git commit -m "fix: fail fast on unresolved deck leaders"
```

---

### Task 3: Deck Thesis Model

**Files:**
- Create: `src/swu_mcp/deck_thesis.py`
- Modify: `src/swu_mcp/deck_service.py`
- Test: `tests/test_deck_thesis.py`

**Interfaces:**
- Produces: `DeckThesis`, `RoleTarget`, `build_deck_thesis(theme: str, leaders: list[dict], base: dict | None, format_name: str, meta_context: dict | None = None) -> DeckThesis`.
- Consumes: `target_packages_for_theme(theme: str) -> set[str]` from `deck_service.py` or move it into `deck_thesis.py` with imports updated.

- [ ] **Step 1: Write failing thesis tests**

Create `tests/test_deck_thesis.py`:

```python
from swu_mcp.deck_thesis import build_deck_thesis
from swu_mcp.deck_service import TWIN_SUNS


def test_kylo_trench_thesis_sets_upgrade_discard_roles() -> None:
    leaders = [
        {
            "display_name": "Kylo Ren - We're Not Done Yet",
            "front_text": "Action [Exhaust]: Discard a card from your hand. If you discarded an upgrade this way, draw a card.",
            "back_text": "When Deployed: Play any number of upgrades from your discard pile on this unit.",
            "aspects": ["Vigilance", "Villainy"],
        },
        {
            "display_name": "Admiral Trench - chk-chk-chk-chk",
            "front_text": "Action [Exhaust]: Discard a card from your hand. Draw a card.",
            "aspects": ["Cunning", "Villainy"],
        },
    ]

    thesis = build_deck_thesis(
        theme="upgrade discard recursion",
        leaders=leaders,
        base={"display_name": "Data Vault - Scarif", "aspects": ["Command"]},
        format_name=TWIN_SUNS,
    )

    assert "discard_engine" in thesis.target_packages
    assert thesis.role_targets["upgrade"].minimum >= 14
    assert thesis.role_targets["upgrade_carrier"].minimum >= 10
    assert thesis.role_targets["defensive_stabilizer"].minimum >= 6


def test_vehicle_theme_sets_vehicle_roles_without_forcing_upgrade_engine() -> None:
    thesis = build_deck_thesis(
        theme="vehicle pilot starfighter aggro",
        leaders=[],
        base=None,
        format_name=TWIN_SUNS,
    )

    assert "pilot_vehicle" in thesis.target_packages
    assert thesis.role_targets["engine_enabler"].minimum >= 8
    assert thesis.role_targets["upgrade"].minimum < 14
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=src uv run pytest tests/test_deck_thesis.py -q
```

Expected: FAIL because `swu_mcp.deck_thesis` does not exist.

- [ ] **Step 3: Implement thesis models and builder**

Create `src/swu_mcp/deck_thesis.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


THEME_TO_PACKAGES: dict[str, set[str]] = {
    "force": {"force_engine"},
    "jedi": {"force_engine"},
    "lightsaber": {"force_engine"},
    "pilot": {"pilot_vehicle"},
    "vehicle": {"pilot_vehicle"},
    "fighter": {"pilot_vehicle"},
    "bounty": {"bounty_hunter"},
    "underworld": {"bounty_hunter"},
    "discard": {"discard_engine"},
    "graveyard": {"discard_engine"},
    "recursion": {"discard_engine"},
    "replay": {"replay_engine"},
    "bounce": {"replay_engine"},
    "when played": {"replay_engine"},
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
    *,
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
        matchup_priorities=tuple(str(item) for item in (meta_context or {}).get("priorities", [])),
        notes=tuple(notes),
    )
```

- [ ] **Step 4: Update deck service imports**

Modify `src/swu_mcp/deck_service.py` to import:

```python
from .deck_thesis import build_deck_thesis, target_packages_for_theme
```

Remove or stop using the duplicate local `target_packages_for_theme` after all references compile.

- [ ] **Step 5: Run thesis tests**

Run:

```bash
PYTHONPATH=src uv run pytest tests/test_deck_thesis.py -q
```

Expected: PASS.

- [ ] **Step 6: Run full tests**

Run:

```bash
PYTHONPATH=src uv run pytest -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/swu_mcp/deck_thesis.py src/swu_mcp/deck_service.py tests/test_deck_thesis.py
git commit -m "feat: derive structured deck thesis"
```

---

### Task 4: Role Tagging And Candidate Pools

**Files:**
- Create: `src/swu_mcp/card_roles.py`
- Modify: `src/swu_mcp/deck_service.py`
- Test: `tests/test_card_roles.py`

**Interfaces:**
- Consumes: `DeckThesis`.
- Produces: `CardRoleProfile`, `roles_for_card(card: dict, thesis: DeckThesis) -> CardRoleProfile`, `build_role_pools(cards: list[dict], thesis: DeckThesis) -> dict[str, list[dict]]`.

- [ ] **Step 1: Write failing role tests**

Create `tests/test_card_roles.py`:

```python
from swu_mcp.card_roles import build_role_pools, roles_for_card
from swu_mcp.deck_thesis import build_deck_thesis
from swu_mcp.deck_service import TWIN_SUNS


def _thesis():
    return build_deck_thesis(
        theme="upgrade discard recursion",
        leaders=[
            {
                "display_name": "Kylo Ren - We're Not Done Yet",
                "front_text": "Discard a card from your hand. If you discarded an upgrade this way, draw a card.",
                "back_text": "Play any number of upgrades from your discard pile on this unit.",
                "aspects": ["Vigilance", "Villainy"],
            }
        ],
        base=None,
        format_name=TWIN_SUNS,
    )


def test_upgrade_gets_upgrade_role() -> None:
    profile = roles_for_card(
        {
            "display_name": "Test Saber",
            "card_type": "Upgrade",
            "front_text": "Attached unit gets +2/+0.",
            "cost": 1,
            "traits": ["ITEM", "WEAPON"],
            "keywords": [],
            "arenas": [],
        },
        _thesis(),
    )

    assert "upgrade" in profile.roles
    assert profile.score_by_role["upgrade"] > 0


def test_low_cost_ground_unit_gets_carrier_and_early_roles() -> None:
    profile = roles_for_card(
        {
            "display_name": "Test Carrier",
            "card_type": "Unit",
            "front_text": "",
            "cost": 2,
            "power": 2,
            "hp": 4,
            "traits": ["SITH"],
            "keywords": ["Sentinel"],
            "arenas": ["Ground"],
        },
        _thesis(),
    )

    assert "early_unit" in profile.roles
    assert "upgrade_carrier" in profile.roles
    assert "defensive_stabilizer" in profile.roles


def test_role_pools_group_cards_by_role() -> None:
    cards = [
        {"display_name": "Upgrade", "card_type": "Upgrade", "front_text": "Attached unit gets +1/+1.", "cost": 1},
        {"display_name": "Carrier", "card_type": "Unit", "front_text": "", "cost": 2, "hp": 4, "arenas": ["Ground"]},
    ]

    pools = build_role_pools(cards, _thesis())

    assert "Upgrade" in [card["display_name"] for card in pools["upgrade"]]
    assert "Carrier" in [card["display_name"] for card in pools["upgrade_carrier"]]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=src uv run pytest tests/test_card_roles.py -q
```

Expected: FAIL because `card_roles.py` does not exist.

- [ ] **Step 3: Implement role tagging**

Create `src/swu_mcp/card_roles.py`:

```python
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
    return " ".join(str(card.get(key) or "") for key in ("front_text", "FrontText", "back_text", "BackText")).lower()


def roles_for_card(card: dict[str, Any], thesis: DeckThesis) -> CardRoleProfile:
    roles: set[str] = set()
    scores: dict[str, float] = {}
    reasons: list[str] = []
    ctype = str(card.get("card_type") or card.get("Type") or "")
    cost = parse_int(card.get("cost") or card.get("Cost"))
    text = _text(card)
    keywords = set(card.get("keywords") or card.get("Keywords") or [])
    arenas = set(card.get("arenas") or card.get("Arenas") or [])
    hp = parse_int(card.get("hp") or card.get("HP")) or 0
    power = parse_int(card.get("power") or card.get("Power")) or 0

    def add(role: str, score: float, reason: str) -> None:
        roles.add(role)
        scores[role] = max(scores.get(role, 0.0), score)
        reasons.append(reason)

    if ctype == "Unit":
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
    if ctype == "Event":
        if any(token in text for token in ("defeat", "damage to a unit", "exhaust", "capture")):
            add("removal", 6.0, "interactive event")
        if any(token in text for token in ("draw", "search the top", "look at the top")):
            add("card_advantage", 5.0, "card selection or draw")
        if any(token in text for token in ("return", "exhaust")):
            add("tempo", 4.0, "tempo text")
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
```

- [ ] **Step 4: Run role tests**

Run:

```bash
PYTHONPATH=src uv run pytest tests/test_card_roles.py -q
```

Expected: PASS.

- [ ] **Step 5: Add role pool integration point**

In `DeckService.generate_deck`, after `pool = list(merged_by_id.values())`, add:

```python
        thesis = build_deck_thesis(
            theme=theme,
            leaders=leaders,
            base=base,
            format_name=normalized_format,
            meta_context=meta_context,
        )
```

The initial task only creates the thesis for later tasks. Do not replace the builder yet.

- [ ] **Step 6: Run full tests**

Run:

```bash
PYTHONPATH=src uv run pytest -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/swu_mcp/card_roles.py src/swu_mcp/deck_service.py tests/test_card_roles.py
git commit -m "feat: classify cards by deckbuilding role"
```

---

### Task 5: Multi-Axis Deck Evaluator

**Files:**
- Create: `src/swu_mcp/deck_evaluator.py`
- Modify: `src/swu_mcp/deck_service.py`
- Test: `tests/test_deck_evaluator.py`

**Interfaces:**
- Consumes: `DeckThesis`, `DeckCardEntry`, existing parsed deck structure.
- Produces: `DeckEvaluation`, `CardDiagnostic`, `evaluate_deck_cards(cards: list[dict], thesis: DeckThesis) -> DeckEvaluation`.

- [ ] **Step 1: Write failing evaluator tests**

Create `tests/test_deck_evaluator.py`:

```python
from swu_mcp.deck_evaluator import evaluate_deck_cards
from swu_mcp.deck_thesis import build_deck_thesis
from swu_mcp.deck_service import TWIN_SUNS


def test_evaluator_flags_too_many_upgrades_without_carriers() -> None:
    thesis = build_deck_thesis(
        theme="upgrade discard recursion",
        leaders=[],
        base=None,
        format_name=TWIN_SUNS,
    )
    cards = [
        {"display_name": f"Upgrade {idx}", "card_type": "Upgrade", "cost": 1, "front_text": "Attached unit gets +1/+1."}
        for idx in range(18)
    ] + [
        {"display_name": "Carrier", "card_type": "Unit", "cost": 2, "hp": 3, "arenas": ["Ground"]}
    ]

    evaluation = evaluate_deck_cards(cards, thesis)

    assert evaluation.axis_scores["upgrade_carrier_risk"] < 50
    assert any("upgrade carriers" in warning.message for warning in evaluation.warnings)


def test_evaluator_rewards_role_coverage() -> None:
    thesis = build_deck_thesis(
        theme="upgrade discard recursion",
        leaders=[],
        base=None,
        format_name=TWIN_SUNS,
    )
    cards = (
        [{"display_name": f"Carrier {idx}", "card_type": "Unit", "cost": 2, "hp": 4, "arenas": ["Ground"]} for idx in range(14)]
        + [{"display_name": f"Upgrade {idx}", "card_type": "Upgrade", "cost": 1, "front_text": "Attached unit gets +1/+1."} for idx in range(16)]
        + [{"display_name": f"Removal {idx}", "card_type": "Event", "cost": 2, "front_text": "Deal 3 damage to a unit."} for idx in range(8)]
    )

    evaluation = evaluate_deck_cards(cards, thesis)

    assert evaluation.axis_scores["role_coverage"] >= 70
    assert evaluation.total_score >= 60
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=src uv run pytest tests/test_deck_evaluator.py -q
```

Expected: FAIL because `deck_evaluator.py` does not exist.

- [ ] **Step 3: Implement evaluator**

Create `src/swu_mcp/deck_evaluator.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .card_roles import roles_for_card
from .deck_thesis import DeckThesis


@dataclass(frozen=True)
class CardDiagnostic:
    card_name: str
    roles: tuple[str, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvaluationWarning:
    code: str
    message: str


@dataclass(frozen=True)
class DeckEvaluation:
    total_score: float
    axis_scores: dict[str, float]
    metrics: dict[str, float]
    card_diagnostics: tuple[CardDiagnostic, ...] = ()
    warnings: tuple[EvaluationWarning, ...] = ()


def _pct(actual: int, target: int) -> float:
    if target <= 0:
        return 100.0
    return max(0.0, min(100.0, (actual / target) * 100.0))


def evaluate_deck_cards(cards: list[dict[str, Any]], thesis: DeckThesis) -> DeckEvaluation:
    role_counts = {role: 0 for role in thesis.role_targets}
    diagnostics: list[CardDiagnostic] = []
    for card in cards:
        profile = roles_for_card(card, thesis)
        for role in profile.roles:
            role_counts[role] = role_counts.get(role, 0) + 1
        diagnostics.append(
            CardDiagnostic(
                card_name=str(card.get("display_name") or card.get("Name") or ""),
                roles=profile.roles,
            )
        )

    role_scores = [
        _pct(role_counts.get(role, 0), target.minimum)
        for role, target in thesis.role_targets.items()
        if target.minimum > 0
    ]
    role_coverage = sum(role_scores) / len(role_scores) if role_scores else 100.0

    upgrade_count = sum(1 for card in cards if str(card.get("card_type") or card.get("Type")) == "Upgrade")
    carrier_count = role_counts.get("upgrade_carrier", 0)
    carrier_ratio = carrier_count / max(upgrade_count, 1)
    upgrade_carrier_risk = 100.0 if upgrade_count <= 4 else max(0.0, min(100.0, carrier_ratio * 100.0))

    warnings: list[EvaluationWarning] = []
    if upgrade_carrier_risk < 70:
        warnings.append(
            EvaluationWarning(
                code="upgrade_carrier_risk",
                message=f"{upgrade_count} upgrades but only {carrier_count} upgrade carriers.",
            )
        )

    axis_scores = {
        "role_coverage": round(role_coverage, 2),
        "upgrade_carrier_risk": round(upgrade_carrier_risk, 2),
    }
    total_score = round((axis_scores["role_coverage"] * 0.7) + (axis_scores["upgrade_carrier_risk"] * 0.3), 2)
    return DeckEvaluation(
        total_score=total_score,
        axis_scores=axis_scores,
        metrics={
            "upgrade_count": float(upgrade_count),
            "upgrade_carrier_count": float(carrier_count),
        },
        card_diagnostics=tuple(diagnostics),
        warnings=tuple(warnings),
    )
```

- [ ] **Step 4: Run evaluator tests**

Run:

```bash
PYTHONPATH=src uv run pytest tests/test_deck_evaluator.py -q
```

Expected: PASS.

- [ ] **Step 5: Attach evaluation to generated output**

In `DeckService.generate_deck`, after `analysis = self.analyze_deck(...)`, add:

```python
        from .deck_evaluator import evaluate_deck_cards

        evaluation = evaluate_deck_cards(expand_entries(parsed.main_deck), thesis)
```

Add to returned dict:

```python
            "evaluation": {
                "total_score": evaluation.total_score,
                "axis_scores": evaluation.axis_scores,
                "metrics": evaluation.metrics,
                "warnings": [
                    {"code": warning.code, "message": warning.message}
                    for warning in evaluation.warnings
                ],
            },
```

- [ ] **Step 6: Run full tests**

Run:

```bash
PYTHONPATH=src uv run pytest -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/swu_mcp/deck_evaluator.py src/swu_mcp/deck_service.py tests/test_deck_evaluator.py
git commit -m "feat: evaluate generated deck quality"
```

---

### Task 6: Local Swap Optimizer

**Files:**
- Create: `src/swu_mcp/deck_optimizer.py`
- Modify: `src/swu_mcp/deck_service.py`
- Test: `tests/test_deck_optimizer.py`

**Interfaces:**
- Consumes: `DeckThesis`, `DeckEvaluation`, role pools.
- Produces: `optimize_card_list(cards: list[dict], role_pools: dict[str, list[dict]], thesis: DeckThesis, max_iterations: int = 20) -> OptimizationResult`.

- [ ] **Step 1: Write failing optimizer test**

Create `tests/test_deck_optimizer.py`:

```python
from swu_mcp.deck_optimizer import optimize_card_list
from swu_mcp.deck_thesis import build_deck_thesis
from swu_mcp.deck_service import TWIN_SUNS


def test_optimizer_swaps_in_missing_upgrade_carrier() -> None:
    thesis = build_deck_thesis(
        theme="upgrade discard recursion",
        leaders=[],
        base=None,
        format_name=TWIN_SUNS,
    )
    cards = [
        {"display_name": f"Upgrade {idx}", "card_type": "Upgrade", "cost": 1, "front_text": "Attached unit gets +1/+1."}
        for idx in range(18)
    ] + [
        {"display_name": f"Vanilla {idx}", "card_type": "Unit", "cost": 5, "hp": 2, "arenas": ["Space"]}
        for idx in range(10)
    ]
    role_pools = {
        "upgrade_carrier": [
            {"display_name": "Durable Carrier", "card_type": "Unit", "cost": 2, "hp": 5, "arenas": ["Ground"]}
        ]
    }

    result = optimize_card_list(cards, role_pools, thesis, max_iterations=3)

    assert result.final_score > result.initial_score
    assert any(swap.added == "Durable Carrier" for swap in result.swaps)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=src uv run pytest tests/test_deck_optimizer.py -q
```

Expected: FAIL because `deck_optimizer.py` does not exist.

- [ ] **Step 3: Implement optimizer**

Create `src/swu_mcp/deck_optimizer.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .deck_evaluator import evaluate_deck_cards
from .deck_thesis import DeckThesis


@dataclass(frozen=True)
class SwapRecord:
    removed: str
    added: str
    reason: str
    score_delta: float


@dataclass(frozen=True)
class OptimizationResult:
    cards: tuple[dict[str, Any], ...]
    initial_score: float
    final_score: float
    swaps: tuple[SwapRecord, ...]


def _name(card: dict[str, Any]) -> str:
    return str(card.get("display_name") or card.get("Name") or "")


def optimize_card_list(
    cards: list[dict[str, Any]],
    role_pools: dict[str, list[dict[str, Any]]],
    thesis: DeckThesis,
    *,
    max_iterations: int = 20,
) -> OptimizationResult:
    current = list(cards)
    initial = evaluate_deck_cards(current, thesis)
    current_score = initial.total_score
    swaps: list[SwapRecord] = []
    candidates = [card for pool in role_pools.values() for card in pool]

    for _ in range(max_iterations):
        best_swap: tuple[float, int, dict[str, Any]] | None = None
        current_names = {_name(card) for card in current}
        for candidate in candidates:
            if _name(candidate) in current_names:
                continue
            for idx, existing in enumerate(current):
                trial = current[:idx] + [candidate] + current[idx + 1 :]
                trial_score = evaluate_deck_cards(trial, thesis).total_score
                delta = trial_score - current_score
                if delta > 0 and (best_swap is None or delta > best_swap[0]):
                    best_swap = (delta, idx, candidate)
        if best_swap is None:
            break
        delta, idx, candidate = best_swap
        removed = current[idx]
        current[idx] = candidate
        current_score += delta
        swaps.append(
            SwapRecord(
                removed=_name(removed),
                added=_name(candidate),
                reason="Improved evaluator score.",
                score_delta=round(delta, 2),
            )
        )

    return OptimizationResult(
        cards=tuple(current),
        initial_score=initial.total_score,
        final_score=round(current_score, 2),
        swaps=tuple(swaps),
    )
```

- [ ] **Step 4: Run optimizer tests**

Run:

```bash
PYTHONPATH=src uv run pytest tests/test_deck_optimizer.py -q
```

Expected: PASS.

- [ ] **Step 5: Add optimizer service entrypoint**

Add method to `DeckService`:

```python
    def optimize_deck(
        self,
        *,
        decklist: str | dict[str, Any],
        theme: str,
        format_name: str = PREMIER,
        only_owned: bool = False,
        max_iterations: int = 20,
    ) -> dict[str, Any]:
        parsed = self.resolve_deck(self.parse_decklist(decklist=decklist, format_name=format_name))
        leaders = [entry.card for entry in parsed.leaders if entry.card]
        base = parsed.bases[0].card if parsed.bases and parsed.bases[0].card else None
        thesis = build_deck_thesis(theme=theme, leaders=leaders, base=base, format_name=parsed.format_name)
        pool = self._candidate_cards(goal_query=compile_goal_query(theme), available_aspects=collect_deck_aspects(parsed), only_owned=only_owned)
        from .card_roles import build_role_pools
        from .deck_optimizer import optimize_card_list
        result = optimize_card_list(expand_entries(parsed.main_deck), build_role_pools(pool, thesis), thesis, max_iterations=max_iterations)
        return {
            "initial_score": result.initial_score,
            "final_score": result.final_score,
            "swaps": [
                {"removed": swap.removed, "added": swap.added, "reason": swap.reason, "score_delta": swap.score_delta}
                for swap in result.swaps
            ],
        }
```

- [ ] **Step 6: Run full tests**

Run:

```bash
PYTHONPATH=src uv run pytest -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/swu_mcp/deck_optimizer.py src/swu_mcp/deck_service.py tests/test_deck_optimizer.py
git commit -m "feat: optimize decks with local swaps"
```

---

### Task 7: Simulation Feedback Reports

**Files:**
- Create: `src/swu_mcp/deck_testing.py`
- Modify: `src/swu_mcp/game_service.py`
- Test: `tests/test_deck_testing.py`

**Interfaces:**
- Produces: `GoldfishReport`, `goldfish_deck(deck_service: DeckService, decklist: str, format_name: str, games: int, seed: int) -> GoldfishReport`.

- [ ] **Step 1: Write failing goldfish test**

Create `tests/test_deck_testing.py`:

```python
from swu_mcp.deck_testing import goldfish_deck
from swu_mcp.deck_service import PREMIER
from swu_mcp.server import deck_service


def test_goldfish_report_is_seeded_and_includes_limitations() -> None:
    decklist = """
    Leaders
    1 Luke Skywalker - Faithful Friend

    Base
    1 Command Center - Lothal

    Main Deck
    3 Alliance Dispatcher
    3 Battlefield Marine
    3 Yavin 4 Infantry
    3 Wing Leader
    3 Open Fire
    3 Resupply
    3 Bright Hope - The Last Transport
    3 Echo Base Defender
    3 General Dodonna - Massassi Group Commander
    3 Rebel Assault
    3 Medal Ceremony
    3 Snowspeeder
    3 Rogue Squadron Skirmisher
    3 Frontline Shuttle
    3 Fleet Lieutenant
    3 Strike True
    2 Home One - Alliance Flagship
    """

    report = goldfish_deck(deck_service, decklist, PREMIER, games=2, seed=1)

    assert report.games == 2
    assert 0 <= report.average_opening_playables
    assert report.limitations
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=src uv run pytest tests/test_deck_testing.py -q
```

Expected: FAIL because `deck_testing.py` does not exist.

- [ ] **Step 3: Implement goldfish report helper**

Create `src/swu_mcp/deck_testing.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
import random

from .deck_service import DeckService, parse_int


@dataclass(frozen=True)
class GoldfishReport:
    games: int
    average_opening_playables: float
    average_opening_resources: float
    limitations: tuple[str, ...]


def goldfish_deck(
    deck_service: DeckService,
    decklist: str,
    format_name: str,
    *,
    games: int = 20,
    seed: int = 1,
) -> GoldfishReport:
    parsed = deck_service.resolve_deck(deck_service.parse_decklist(decklist=decklist, format_name=format_name))
    library = [entry.card for entry in parsed.main_deck for _ in range(entry.quantity) if entry.card]
    rng = random.Random(seed)
    playable_counts: list[int] = []
    resource_counts: list[int] = []
    for _ in range(games):
        shuffled = list(library)
        rng.shuffle(shuffled)
        hand = shuffled[:6]
        playable_counts.append(sum(1 for card in hand if (parse_int(card.get("cost")) or 99) <= 2))
        resource_counts.append(len(hand))
    return GoldfishReport(
        games=games,
        average_opening_playables=round(sum(playable_counts) / max(games, 1), 2),
        average_opening_resources=round(sum(resource_counts) / max(games, 1), 2),
        limitations=(
            "Goldfish report checks opening hand texture only.",
            "Current simulator does not fully model every nested optional trigger.",
        ),
    )
```

- [ ] **Step 4: Run goldfish tests**

Run:

```bash
PYTHONPATH=src uv run pytest tests/test_deck_testing.py -q
```

Expected: PASS.

- [ ] **Step 5: Add service wrapper later consumed by MCP**

Add to `DeckService`:

```python
    def goldfish_deck_report(
        self,
        *,
        decklist: str,
        format_name: str = PREMIER,
        games: int = 20,
        seed: int = 1,
    ) -> dict[str, Any]:
        from .deck_testing import goldfish_deck

        report = goldfish_deck(self, decklist, format_name, games=games, seed=seed)
        return {
            "games": report.games,
            "average_opening_playables": report.average_opening_playables,
            "average_opening_resources": report.average_opening_resources,
            "limitations": list(report.limitations),
        }
```

- [ ] **Step 6: Run full tests**

Run:

```bash
PYTHONPATH=src uv run pytest -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/swu_mcp/deck_testing.py src/swu_mcp/deck_service.py tests/test_deck_testing.py
git commit -m "feat: add deck goldfish reports"
```

---

### Task 8: Archetype Registry And Benchmarks

**Files:**
- Create: `src/swu_mcp/archetypes.py`
- Create: `tests/test_archetypes.py`
- Modify: `src/swu_mcp/deck_thesis.py`

**Interfaces:**
- Produces: `KnownArchetype`, `known_archetypes() -> list[KnownArchetype]`, `match_archetype(leaders: list[dict], format_name: str) -> KnownArchetype | None`.
- Consumes: `DeckThesis.signature_cards`.

- [ ] **Step 1: Write failing archetype tests**

Create `tests/test_archetypes.py`:

```python
from swu_mcp.archetypes import match_archetype
from swu_mcp.deck_thesis import build_deck_thesis
from swu_mcp.deck_service import TWIN_SUNS


def test_matches_kylo_trench_archetype() -> None:
    leaders = [
        {"display_name": "Kylo Ren - We're Not Done Yet", "name": "Kylo Ren", "subtitle": "We're Not Done Yet"},
        {"display_name": "Admiral Trench - chk-chk-chk-chk", "name": "Admiral Trench", "subtitle": "chk-chk-chk-chk"},
    ]

    archetype = match_archetype(leaders, TWIN_SUNS)

    assert archetype is not None
    assert archetype.archetype_id == "twin-suns-kylo-trench-upgrades"


def test_thesis_includes_archetype_signature_cards() -> None:
    leaders = [
        {"display_name": "Kylo Ren - We're Not Done Yet", "name": "Kylo Ren", "subtitle": "We're Not Done Yet"},
        {"display_name": "Admiral Trench - chk-chk-chk-chk", "name": "Admiral Trench", "subtitle": "chk-chk-chk-chk"},
    ]

    thesis = build_deck_thesis(theme="upgrade discard recursion", leaders=leaders, base=None, format_name=TWIN_SUNS)

    assert "Snapshot Reflexes" in thesis.signature_cards
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=src uv run pytest tests/test_archetypes.py -q
```

Expected: FAIL because `archetypes.py` does not exist.

- [ ] **Step 3: Implement archetype registry**

Create `src/swu_mcp/archetypes.py`:

```python
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
```

- [ ] **Step 4: Add archetype signatures to thesis**

In `deck_thesis.py`, import:

```python
from .archetypes import match_archetype
```

Inside `build_deck_thesis`, before return:

```python
    archetype = match_archetype(leaders, format_name)
    signature_cards: tuple[str, ...] = ()
    if archetype is not None:
        packages |= set(archetype.package_targets)
        signature_cards = archetype.signature_cards
        for role, ideal in archetype.role_targets.items():
            current = role_targets.get(role)
            if current is not None:
                role_targets[role] = _target(current.minimum, max(current.ideal, ideal), current.maximum)
```

Set the returned `DeckThesis.signature_cards` to `signature_cards`.

- [ ] **Step 5: Run archetype tests**

Run:

```bash
PYTHONPATH=src uv run pytest tests/test_archetypes.py -q
```

Expected: PASS.

- [ ] **Step 6: Run full tests**

Run:

```bash
PYTHONPATH=src uv run pytest -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/swu_mcp/archetypes.py src/swu_mcp/deck_thesis.py tests/test_archetypes.py
git commit -m "feat: seed deck thesis from known archetypes"
```

---

### Task 9: Optimized MCP Tools

**Files:**
- Modify: `src/swu_mcp/server.py`
- Modify: `src/swu_mcp/deck_service.py`
- Test: `tests/test_server_tools.py`

**Interfaces:**
- Produces MCP-callable wrappers: `swu_evaluate_deck`, `swu_optimize_deck`, `swu_run_deck_goldfish`, `swu_known_archetypes`.

- [ ] **Step 1: Write failing tool tests**

Create `tests/test_server_tools.py`:

```python
from swu_mcp.archetypes import known_archetypes
from swu_mcp.server import swu_known_archetypes


def test_known_archetypes_tool_returns_records() -> None:
    result = swu_known_archetypes()

    assert result["count"] == len(known_archetypes())
    assert any(item["archetype_id"] == "twin-suns-kylo-trench-upgrades" for item in result["archetypes"])
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=src uv run pytest tests/test_server_tools.py -q
```

Expected: FAIL because `swu_known_archetypes` is not exposed.

- [ ] **Step 3: Add MCP tool wrappers**

Add to `src/swu_mcp/server.py`:

```python
@mcp.tool(description="List known Star Wars Unlimited archetype records supported by the deckbuilder.")
def swu_known_archetypes() -> dict:
    from .archetypes import known_archetypes

    archetypes = known_archetypes()
    return {
        "count": len(archetypes),
        "archetypes": [
            {
                "archetype_id": archetype.archetype_id,
                "format": archetype.format_name,
                "name": archetype.name,
                "description": archetype.description,
                "signature_cards": list(archetype.signature_cards),
                "package_targets": list(archetype.package_targets),
                "last_reviewed": archetype.last_reviewed,
            }
            for archetype in archetypes
        ],
    }


@mcp.tool(description="Optimize an uploaded or supplied decklist through evaluator-backed local swaps.")
def swu_optimize_deck(
    decklist: str,
    theme: str,
    format_name: str = "premier",
    only_owned: bool = False,
    max_iterations: int = 20,
) -> dict:
    return deck_service.optimize_deck(
        decklist=decklist,
        theme=theme,
        format_name=format_name,
        only_owned=only_owned,
        max_iterations=max_iterations,
    )


@mcp.tool(description="Run a seeded goldfish report for a decklist.")
def swu_run_deck_goldfish(
    decklist: str,
    format_name: str = "premier",
    games: int = 20,
    seed: int = 1,
) -> dict:
    return deck_service.goldfish_deck_report(
        decklist=decklist,
        format_name=format_name,
        games=games,
        seed=seed,
    )
```

- [ ] **Step 4: Run tool tests**

Run:

```bash
PYTHONPATH=src uv run pytest tests/test_server_tools.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full tests**

Run:

```bash
PYTHONPATH=src uv run pytest -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/swu_mcp/server.py tests/test_server_tools.py
git commit -m "feat: expose optimized deckbuilder tools"
```

---

### Task 10: Two-Stage Leader Pair Ranking

**Files:**
- Modify: `src/swu_mcp/deck_service.py`
- Test: `tests/test_leader_pair_ranking.py`

**Interfaces:**
- Produces: `rank_leader_pairs(..., include_decks=False)` that shortlists without brewing every pair; full deck generation only happens for top finalists or when `include_decks=True`.

- [ ] **Step 1: Write failing performance behavior test**

Create `tests/test_leader_pair_ranking.py`:

```python
from swu_mcp.deck_service import DeckService, TWIN_SUNS


class DummyDeckService(DeckService):
    def __init__(self):
        self.generate_calls = 0

    def generate_deck(self, **kwargs):
        self.generate_calls += 1
        return {
            "analysis": {"synergy_score": 50, "interaction_density": 10, "average_cost": 2.5, "deck_size": 80, "trait_breakdown": {}, "role_breakdown": {}, "available_aspects": []},
            "validation": {"aspect_penalties": {"total_extra_resource_burden": 0}},
            "deck_holoscan": "",
        }


def test_rank_leader_pairs_shortlist_limits_full_brews() -> None:
    service = DummyDeckService()

    assert hasattr(service, "_leader_pair_fast_score")
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=src uv run pytest tests/test_leader_pair_ranking.py -q
```

Expected: FAIL because `_leader_pair_fast_score` does not exist.

- [ ] **Step 3: Add fast score helper**

Add to `DeckService`:

```python
    def _leader_pair_fast_score(
        self,
        first: dict[str, Any],
        second: dict[str, Any],
        *,
        theme: str,
        target_packages: set[str],
    ) -> float:
        text = " ".join(
            str(card.get(key) or "")
            for card in (first, second)
            for key in ("display_name", "front_text", "back_text", "epic_action")
        ).lower()
        score = 0.0
        for token in tokenize_text(theme):
            if token in text:
                score += 3.0
        roles = set()
        for leader in (first, second):
            for package, role_map in LEADER_PACKAGE_ROLES.items():
                for role_name, patterns in role_map.items():
                    if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
                        roles.add((package, role_name))
        score += sum(5.0 for package, _ in roles if package in target_packages)
        score += len(set(first.get("aspects") or []) | set(second.get("aspects") or []))
        return score
```

- [ ] **Step 4: Use fast score before full brew**

Inside `rank_leader_pairs`, before full brewing loop:

```python
        scored_pairs = [
            (
                self._leader_pair_fast_score(first, second, theme=theme, target_packages=target_packages),
                first,
                second,
                shared,
            )
            for first, second, shared in pairs
        ]
        scored_pairs.sort(key=lambda item: item[0], reverse=True)
        finalist_count = max(top_k * 3, top_k)
        finalist_pairs = [(first, second, shared) for _, first, second, shared in scored_pairs[:finalist_count]]
```

Change the brewing loop to iterate `for first, second, shared in finalist_pairs:`.

- [ ] **Step 5: Strengthen test with real ranking smoke test**

Append to `tests/test_leader_pair_ranking.py`:

```python
def test_fast_score_prefers_theme_text() -> None:
    service = DummyDeckService()
    first = {"display_name": "Discard Leader", "front_text": "Discard a card from your hand.", "aspects": ["Villainy"]}
    second = {"display_name": "Recursion Leader", "back_text": "Play a card from your discard pile.", "aspects": ["Villainy"]}
    weak = {"display_name": "Blank Leader", "front_text": "", "aspects": ["Villainy"]}

    strong = service._leader_pair_fast_score(first, second, theme="discard recursion", target_packages={"discard_engine"})
    weak_score = service._leader_pair_fast_score(first, weak, theme="discard recursion", target_packages={"discard_engine"})

    assert strong > weak_score
```

- [ ] **Step 6: Run ranking tests**

Run:

```bash
PYTHONPATH=src uv run pytest tests/test_leader_pair_ranking.py -q
```

Expected: PASS.

- [ ] **Step 7: Run full tests**

Run:

```bash
PYTHONPATH=src uv run pytest -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/swu_mcp/deck_service.py tests/test_leader_pair_ranking.py
git commit -m "perf: shortlist leader pairs before brewing"
```

---

## Self-Review

Spec coverage:

- Canonical identity and ownership are covered in Task 1.
- Fail-fast leader/base resolution and illegal deck prevention are covered in Task 2.
- Deck thesis is covered in Task 3.
- Role-aware candidate pools are covered in Task 4.
- Multi-axis evaluation is covered in Task 5.
- Iterative swap optimization is covered in Task 6.
- Simulation feedback starts with deterministic goldfish reporting in Task 7.
- Archetype and meta layer starts with registry and signature card integration in Task 8.
- MCP surfaces are covered in Task 9.
- Leader-pair ranking performance is covered in Task 10.

Type consistency:

- `CanonicalCardKey`, `OwnedPrinting`, `DeckThesis`, `RoleTarget`, `CardRoleProfile`, `DeckEvaluation`, `OptimizationResult`, and `KnownArchetype` are introduced before later tasks consume them.
- New service methods return plain dicts at MCP boundaries and typed dataclasses internally.
- Existing `DeckService` remains the integration point for server tools.

Validation commands:

```bash
cd "/Users/adamsteen/projects/mcps/SWU-MCP codename Hyperspeed"
PYTHONPATH=src uv run pytest -q
```

Expected final result: all tests pass after every task.
