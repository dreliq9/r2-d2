from __future__ import annotations

import json
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from .card_service import CardService
from .collection_service import CollectionService
from .interaction_glossary import (
    _filter_aspect_needs,
    needs_set as interaction_needs_set,
    provides_set as interaction_provides_set,
)

INTERACTION_WEIGHT = 0.15
INTERACTION_PAYOFF_W = 8.0
INTERACTION_ENABLER_W = 8.0
INTERACTION_TRAIT_W = 0.5
INTERACTION_CAP_PER_PAIR = 1

POWER_WEIGHT = 1.0
BLANK_TEXT_PENALTY = -4.0
RARITY_BUMP = {"Common": 0.0, "Uncommon": 1.0, "Rare": 3.0, "Legendary": 5.0, "Special": 2.0}
# Premier's larger min deck and 3-of copies tolerate a higher curve. Twin Suns
# is singleton at 80+ cards, so community guides recommend a noticeably lower
# curve to absorb the extra variance — see Nerdologists, Garbage Rollers.
TARGET_AVG_COST_PREMIER = 3.4
TARGET_AVG_COST_TWIN_SUNS = 2.7
TARGET_AVG_COST = TARGET_AVG_COST_PREMIER  # back-compat for existing references
COST_OVERRUN_W = -3.0
# Off-aspect singletons hurt twice in Twin Suns: you pay the +2 *and* you can't
# resource around it because there's only one copy. Stronger negative weight.
OFF_ASPECT_PER_ICON_PREMIER = -25.0
OFF_ASPECT_PER_ICON_TWIN_SUNS = -40.0
# Twin Suns guide hooks (official article + community): keywords that close
# games quickly matter more because singleton makes finishers harder to find.
TWIN_SUNS_BASE_PRESSURE_KEYWORDS = {"Ambush", "Overwhelm", "Saboteur", "Raid"}
TWIN_SUNS_BASE_PRESSURE_BONUS = 3.0
TWIN_SUNS_LEADER_SYNERGY_BONUS = 4.0

# Per-aspect role identity (synthesized from SWU community deckbuilding guides:
# Dexerto archetype guide, Card Gamer aspects guide, The Fifth Trooper, and
# Garbage Rollers' color power rankings). Cards that express their aspect's
# signature role get a small consistency bonus on top of being on-aspect —
# this nudges the generator toward cards that actually *play* the aspect's
# strategy rather than just sharing its color.
ASPECT_AFFINITY: dict[str, dict[str, set[str]]] = {
    "Aggression": {
        "keywords": {"Saboteur", "Raid", "Overwhelm"},
        "text_tokens": {"deal ", " damage to a unit", " damage to a base"},
    },
    "Vigilance": {
        "keywords": {"Sentinel", "Shielded", "Restore", "Grit"},
        "text_tokens": {"shield token", "heal"},
    },
    "Command": {
        "keywords": {"Restore"},
        "text_tokens": {"create", "ready a", "extra resource", " token"},
    },
    "Cunning": {
        "keywords": {"Ambush"},
        "text_tokens": {"discard", "exhaust", "return"},
    },
    "Heroism": {
        # No single keyword owns Heroism — its identity is wide boards.
        "keywords": set(),
        "text_tokens": {"for each friendly", "for each unit", "each other friendly"},
    },
    "Villainy": {
        "keywords": set(),
        "text_tokens": {"when defeated", "sacrifice"},
    },
}
ASPECT_AFFINITY_BONUS = 2.5

# Color-pie analog: which aspect "owns" each keyword (primary printing home).
# Derived empirically from a 463-card collection analysis (counted only the 4
# neutral aspects, since Heroism/Villainy overlay any neutral). When a card's
# keyword matches its aspect's primary, give a small consistency bonus.
PRIMARY_KEYWORD_BY_ASPECT: dict[str, set[str]] = {
    "Aggression": {"Overwhelm", "Raid", "Saboteur"},
    "Vigilance":  {"Sentinel", "Shielded", "Grit"},
    "Command":    {"Restore", "Ambush"},
    "Cunning":    {"Hidden", "Ambush", "Piloting"},
    "Heroism": set(),   # moral aspects don't own keywords
    "Villainy": set(),
}
COLOR_PIE_BONUS = 1.5

# Keyword synergy pairs: when a card has BOTH keywords from a designed-synergy
# cluster, the whole is more than the sum of parts. Bonuses stack across pairs.
# Pairs derived from co-occurrence analysis of the collection plus known
# functional combos (anti-defense bypass, fortress walls, sustain engines).
KEYWORD_SYNERGY_PAIRS: list[frozenset[str]] = [
    frozenset({"Hidden", "Raid"}),         # stealth burst
    frozenset({"Saboteur", "Sentinel"}),   # bypass + provoke
    frozenset({"Saboteur", "Raid"}),       # bigger anti-defense burst
    frozenset({"Saboteur", "Ambush"}),     # surprise that ignores Sentinel
    frozenset({"Overwhelm", "Raid"}),      # finisher push
    frozenset({"Grit", "Sentinel"}),       # walls that grow when hit
    frozenset({"Grit", "Shielded"}),       # absorb-then-grow fortress
    frozenset({"Grit", "Restore"}),        # damaged healer
    frozenset({"Grit", "Overwhelm"}),      # grow + push excess
    frozenset({"Restore", "Sentinel"}),    # protected healer
    frozenset({"Restore", "Shielded"}),    # self-protecting healer
    frozenset({"Hidden", "Shielded"}),     # double untargetable
    frozenset({"Hidden", "Ambush"}),       # surprise unblockable
    frozenset({"Ambush", "Restore"}),      # enter and heal
]
KEYWORD_SYNERGY_BONUS = 2.0

# Theme keyword → combo package(s) it implies. Used by rank_leader_pairs to
# weight package-fit when scoring brewed pairings against a stated theme.
THEME_TO_PACKAGES: dict[str, set[str]] = {
    "force":       {"force_engine"},
    "jedi":        {"force_engine"},
    "lightsaber":  {"force_engine"},
    "indirect":    {"indirect_damage"},
    "bounty":      {"bounty_hunter", "indirect_damage"},
    "hunter":      {"bounty_hunter"},
    "defeat":      {"when_defeated"},
    "sacrifice":   {"when_defeated"},
    "exploit":     {"when_defeated"},
    "death":       {"when_defeated"},
    "pilot":       {"pilot_vehicle"},
    "vehicle":     {"pilot_vehicle"},
    "fighter":     {"pilot_vehicle"},
    "token":       {"token_swarm"},
    "swarm":       {"token_swarm"},
    "wide":        {"token_swarm"},
    "ramp":        {"cost_reduction"},
    "discount":    {"cost_reduction"},
    "cheap":       {"cost_reduction"},
    "sentinel":    {"fortress"},
    "defense":     {"fortress"},
    "defensive":   {"fortress"},
    "wall":        {"fortress"},
    "fortress":    {"fortress"},
    "control":     {"fortress"},
    "exhaust":     {"exhaust_engine"},
    "ready":       {"exhaust_engine"},
    "tap":         {"exhaust_engine"},
    "mandalorian": {"mandalorian"},
    "mando":       {"mandalorian"},
    "bounce":      {"replay_engine"},
    "replay":      {"replay_engine"},
    "re-trigger":  {"replay_engine"},
    "retrigger":   {"replay_engine"},
    "when played": {"replay_engine"},
    "grit":        {"self_damage_engine"},
    "self-damage": {"self_damage_engine"},
    "self damage": {"self_damage_engine"},
    "on attack":   {"attack_engine"},
    "attack-engine":{"attack_engine"},
    "free attack": {"attack_engine"},
    "discard":     {"discard_engine"},
    "graveyard":   {"discard_engine"},
    "recursion":   {"discard_engine"},
    "from discard":{"discard_engine"},
}
THEME_FIT_PER_MATCH = 0.5
THEME_FIT_CAP = 25.0

# Leader-level roles per combo package. The leader-pair ranker uses these to
# detect "closed loops" — pairs where one leader generates the resource and
# the other consumes/pays-off on it. Closed loops score higher than two
# leaders that happen to touch the same package independently.
LEADER_PACKAGE_ROLES: dict[str, dict[str, list[str]]] = {
    "force_engine": {
        "generator": [r"create your Force token", r"create a Force token"],
        "consumer":  [r"use the Force"],
        "payoff":    [r"Force unit", r"Jedi unit", r"if you used the Force"],
    },
    "exhaust_engine": {
        # "Action [Exhaust]:" pays for the leader's own action with its own
        # exhaust — that doesn't generate exhaust state on a target. Look for
        # effects that exhaust *another* unit.
        "generator": [
            r"exhaust an enemy",
            r"exhaust a non-leader unit",
            r"exhaust a unit\b",
            r"exhaust each",
        ],
        "consumer":  [r"\bready a ", r"\bready an ", r"\bready that "],
        "payoff":    [r"if you control an exhausted", r"another exhausted"],
    },
    "token_swarm": {
        "generator": [r"create (a|an|\d+) [\w\- ]*?token"],
        "consumer":  [],
        # "if you control 6 or more" without a noun matches epic-deploy text
        # ("6 or more resources"). Require a unit/friendly object.
        "payoff":    [r"for each friendly", r"for each unit", r"if you control \d+ or more (?:friendly )?units"],
    },
    "indirect_damage": {
        "generator": [r"deal \d+ indirect"],
        "consumer":  [],
        "payoff":    [r"indirect damage you deal", r"when indirect damage is dealt"],
    },
    "when_defeated": {
        "generator": [r"defeat (a|an|target|each|all|up to)( [\w'-]+){0,3} unit"],
        "consumer":  [],
        "payoff":    [r"When Defeated"],
    },
    # Implicit synergy: bounce/replay enablers don't mention "When Played"
    # but every When Played card becomes a replay-payoff target. Qui-Gon
    # Jinn's "Return a friendly non-leader unit" is the canonical leader
    # enabler. The payoff side (When Played) is handled at the deck level
    # via the combo package's matchers, not at the leader-action level —
    # most leaders don't have When Played effects since they enter via
    # epic deploys.
    "replay_engine": {
        "generator": [
            r"return a (friendly )?(non-leader )?unit",
            r"return [\w'\- ]+ to its owner",
            r"return [\w'\- ]+ to your hand",
            r"play a (unit|card) from your (hand|discard)",
            r"play [\w'\- ]+ for free",
        ],
        "consumer":  [],
        "payoff":    [r"When Played:"],
    },
    # Self-damage enablers (Asajj Ventress action, etc.) fuel Grit + damage
    # payoffs. Most leaders don't have Grit text directly, so payoff side
    # at the leader level is rare.
    "self_damage_engine": {
        "generator": [
            r"deal \d+ damage to a friendly",
            r"deal \d+ damage to a unit you control",
        ],
        "consumer":  [],
        "payoff":    [r"\bGrit\b", r"for each damage", r"while damaged"],
    },
    # Free-attack effects pair with any On Attack: triggered text. Avar
    # Kriss doesn't grant attacks but other Force leaders enable repeat
    # attacks via "use the Force" effects on units.
    "attack_engine": {
        "generator": [
            r"attack with a (friendly )?[\w\- ]*unit",
            r"may attack with",
            r"even if (it'?s? )?exhausted",
        ],
        "consumer":  [],
        "payoff":    [r"On Attack:"],
    },
    # Discard sources + graveyard recursion. Kylo Ren leader is the main
    # Heroism/Villainy generator. Payoffs trigger off cards in discard.
    "discard_engine": {
        "generator": [
            r"discard \d+ card",
            r"discard a card",
            r"discard your hand",
        ],
        "consumer":  [],
        "payoff":    [
            r"from your discard pile",
            r"from the discard pile",
        ],
    },
}
LEADER_LOOP_CLOSED_BONUS = 5.0    # generator + consumer present on the pair
LEADER_LOOP_PAYOFF_BONUS = 3.0    # generator + payoff present on the pair
LEADER_LOOP_TOUCH_BONUS  = 1.0    # at least one leader touches the package

PREMIER = "premier"
TWIN_SUNS = "twin_suns"
SUPPORTED_FORMATS = {PREMIER, TWIN_SUNS}

_COPY_OVERRIDE_RE = __import__("re").compile(
    r"a deck can have (?:up to (\d+)|any number of) copies of this card",
    __import__("re").IGNORECASE,
)


def card_copy_override(card: dict | None) -> int | None:
    """Return the per-card copy limit override declared on the card text, if any.
    `None` means no override (use the format default). A very large int models
    'any number'."""
    if not card:
        return None
    text = str(card.get("front_text") or card.get("FrontText") or "")
    if not text:
        return None
    m = _COPY_OVERRIDE_RE.search(text)
    if not m:
        return None
    if m.group(1):
        return int(m.group(1))
    return 999  # "any number"

PREMIER_MAIN_DECK_MIN = 50
PREMIER_SIDEBOARD_MAX = 10
PREMIER_COPY_LIMIT = 3
PREMIER_LEADER_COUNT = 1
TWIN_SUNS_MAIN_DECK_MIN = 80
TWIN_SUNS_LEADER_COUNT = 2
STARTING_HAND_SIZE = 6
ASPECT_PENALTY_PER_MISSING_ICON = 2

SECTION_ALIASES = {
    "leader": "leaders",
    "leaders": "leaders",
    "base": "bases",
    "bases": "bases",
    "main": "main_deck",
    "deck": "main_deck",
    "draw": "main_deck",
    "draw deck": "main_deck",
    "main deck": "main_deck",
    "cards": "main_deck",
    "sideboard": "sideboard",
    "side": "sideboard",
}

GOAL_QUERY_HINTS = {
    "removal": "defeat damage",
    "aggro": "attack when played",
    "control": "defeat exhaust return",
    "midrange": "unit on attack",
    "token": "experience shield token",
    "sentinel": "sentinel",
    "space": "space",
    "ground": "ground",
    "restore": "restore",
}

ROLE_PATTERNS = {
    "removal": ("defeat", "deal", "damage to a unit", "capture"),
    "base_pressure": ("damage to a base", "enemy base", "opponent's base"),
    "card_advantage": ("draw", "search the top", "look at the top", "ready"),
    "defense": ("restore", "shield", "sentinel", "heal"),
    "tempo": ("return", "exhaust", "discard", "ready this unit"),
}

MATCHUP_PROFILES = {
    "aggro": {
        "roles": {"removal": 8, "defense": 8, "board_presence": 4},
        "keywords": {"Restore": 5, "Sentinel": 5},
        "arena": {"Ground": 3},
        "early_curve": 6,
    },
    "midrange": {
        "roles": {"board_presence": 7, "tempo": 5, "removal": 5},
        "keywords": {"Ambush": 3, "Raid": 3},
        "arena": {"Ground": 2, "Space": 2},
        "early_curve": 2,
    },
    "control": {
        "roles": {"card_advantage": 8, "base_pressure": 5, "tempo": 5},
        "keywords": {"Saboteur": 4},
        "arena": {"Space": 1},
        "early_curve": 0,
    },
    "space": {
        "roles": {"board_presence": 5, "removal": 4},
        "keywords": {"Ambush": 2},
        "arena": {"Space": 8},
        "early_curve": 2,
    },
    "tokens": {
        "roles": {"removal": 6, "tempo": 4},
        "keywords": {"Sentinel": 3},
        "arena": {"Ground": 2},
        "early_curve": 2,
    },
}

STOPWORDS = {
    "and",
    "for",
    "the",
    "with",
    "into",
    "more",
    "less",
    "your",
    "this",
    "that",
    "from",
    "against",
    "matchup",
    "matchups",
    "improve",
}


@dataclass(slots=True)
class DeckCardEntry:
    quantity: int
    name: str
    zone: str
    set_code: str | None = None
    card_number: str | None = None
    card: dict[str, Any] | None = None

    @property
    def lookup_id(self) -> str | None:
        if self.card:
            return str(self.card["lookup_id"])
        if self.set_code and self.card_number:
            return f"{self.set_code.upper()}/{normalize_lookup_number(self.card_number)}"
        return None

    @property
    def display_name(self) -> str:
        if self.card:
            return str(self.card["display_name"])
        return self.name


@dataclass(slots=True)
class ParsedDeck:
    format_name: str
    leaders: list[DeckCardEntry] = field(default_factory=list)
    bases: list[DeckCardEntry] = field(default_factory=list)
    main_deck: list[DeckCardEntry] = field(default_factory=list)
    sideboard: list[DeckCardEntry] = field(default_factory=list)
    title: str | None = None


@dataclass(slots=True)
class GameCardState:
    instance_id: str
    lookup_id: str
    name: str
    zone: str
    ready: bool = True
    damage: int = 0
    experience: int = 0
    shield: int = 0
    power_bonus: int = 0
    hp_bonus: int = 0
    granted_keywords: list[str] = field(default_factory=list)
    arena: str | None = None
    deployed: bool = True
    attached_to_instance_id: str | None = None
    attached_to_name: str | None = None


@dataclass(slots=True)
class DeckSession:
    session_id: str
    deck: ParsedDeck
    card_index: dict[str, dict[str, Any]]
    library: list[str]
    next_instance_number: int = 1
    opening_hand_size: int = STARTING_HAND_SIZE
    hand: list[str] = field(default_factory=list)
    discard: list[str] = field(default_factory=list)
    resources: list[GameCardState] = field(default_factory=list)
    ground_arena: list[GameCardState] = field(default_factory=list)
    space_arena: list[GameCardState] = field(default_factory=list)
    upgrades: list[GameCardState] = field(default_factory=list)
    leaders: list[GameCardState] = field(default_factory=list)
    bases: list[GameCardState] = field(default_factory=list)
    mulligans_taken: int = 0
    notes: list[str] = field(default_factory=list)

    def zone_cards(self, zone: str) -> list[dict[str, Any]]:
        if zone == "library":
            return [self.card_index[lookup_id] for lookup_id in self.library]
        if zone == "hand":
            return [self.card_index[lookup_id] for lookup_id in self.hand]
        if zone == "discard":
            return [self.card_index[lookup_id] for lookup_id in self.discard]
        if zone == "ground":
            return [self.card_index[card.lookup_id] for card in self.ground_arena]
        if zone == "space":
            return [self.card_index[card.lookup_id] for card in self.space_arena]
        if zone == "upgrade":
            return [self.card_index[card.lookup_id] for card in self.upgrades]
        raise ValueError(f"Unknown zone: {zone}")

    def next_instance_id(self, prefix: str = "card") -> str:
        instance_id = f"{prefix}-{self.next_instance_number}"
        self.next_instance_number += 1
        return instance_id

    def board_snapshot(self) -> dict[str, Any]:
        return {
            "ground_arena": [summarize_game_card(card, self.card_index) for card in self.ground_arena],
            "space_arena": [summarize_game_card(card, self.card_index) for card in self.space_arena],
            "upgrades": [summarize_game_card(card, self.card_index) for card in self.upgrades],
            "leaders": [summarize_game_card(card, self.card_index) for card in self.leaders],
            "bases": [summarize_game_card(card, self.card_index) for card in self.bases],
            "resources": [summarize_game_card(card, self.card_index) for card in self.resources],
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "format": self.deck.format_name,
            "leaders": [entry.display_name for entry in self.deck.leaders],
            "base": self.deck.bases[0].display_name if self.deck.bases else None,
            "main_deck_size": sum(entry.quantity for entry in self.deck.main_deck),
            "sideboard_size": sum(entry.quantity for entry in self.deck.sideboard),
            "library_count": len(self.library),
            "hand_count": len(self.hand),
            "discard_count": len(self.discard),
            "ground_count": len(self.ground_arena),
            "space_count": len(self.space_arena),
            "upgrade_count": len(self.upgrades),
            "resource_count": len(self.resources),
            "ready_resources": sum(1 for resource in self.resources if resource.ready),
            "ready_units": sum(1 for card in self.ground_arena + self.space_arena if card.ready),
            "mulligans_taken": self.mulligans_taken,
            "hand": [summarize_for_zone(self.card_index[lookup_id]) for lookup_id in self.hand],
            "discard": [summarize_for_zone(self.card_index[lookup_id]) for lookup_id in self.discard[-10:]],
            **self.board_snapshot(),
        }


class DeckService:
    def __init__(
        self,
        card_service: CardService,
        collection_service: CollectionService | None = None,
    ) -> None:
        self.card_service = card_service
        self.collection_service = collection_service
        self.sessions: dict[str, DeckSession] = {}

    def _candidate_is_owned(self, candidate: dict[str, Any], *, minimum: int = 1) -> bool:
        if self.collection_service is None:
            return True
        set_code = candidate.get("set_code") or ""
        number = candidate.get("number") or ""
        if not set_code or not number:
            return False
        return self.collection_service.is_owned(str(set_code), str(number), quantity=minimum)

    def _candidate_owned_count(self, candidate: dict[str, Any]) -> int:
        if self.collection_service is None:
            return 0
        set_code = candidate.get("set_code") or ""
        number = candidate.get("number") or ""
        if not set_code or not number:
            return 0
        return self.collection_service.owned_count(str(set_code), str(number))

    def _safe_lookup(self, card: dict[str, Any]) -> dict[str, Any] | None:
        try:
            return self.card_service.lookup_card(
                set_code=card.get("set_code"), card_number=card.get("number")
            )
        except Exception:
            return None

    def upload_deck(
        self,
        decklist: str | dict[str, Any],
        *,
        session_id: str = "default",
        format_name: str = PREMIER,
        shuffle: bool = True,
        draw_opening_hand: bool = False,
    ) -> dict[str, Any]:
        self.card_service._ensure_local_catalog()
        parsed = self.parse_decklist(decklist=decklist, format_name=format_name)
        resolved = self.resolve_deck(parsed)
        validation = self.validate_parsed_deck(resolved)
        session = self._build_session(session_id=session_id, deck=resolved, shuffle=shuffle)

        if draw_opening_hand:
            self._draw_cards(session, session.opening_hand_size)

        self.sessions[session_id] = session
        return {
            "session_id": session_id,
            "format": resolved.format_name,
            "validation": validation,
            "deck_summary": summarize_deck(resolved),
            "state": session.snapshot(),
        }

    def draw_card(self, *, session_id: str = "default", count: int = 1) -> dict[str, Any]:
        session = self._get_session(session_id)
        drawn_cards = self._draw_cards(session, count)
        return {
            "session_id": session_id,
            "drawn": [summarize_for_zone(card) for card in drawn_cards],
            "state": session.snapshot(),
        }

    def view_hand(self, *, session_id: str = "default") -> dict[str, Any]:
        session = self._get_session(session_id)
        return session.snapshot()

    def view_board(self, *, session_id: str = "default") -> dict[str, Any]:
        session = self._get_session(session_id)
        return {
            "session_id": session_id,
            "format": session.deck.format_name,
            "state": session.board_snapshot(),
        }

    def mulligan(self, *, session_id: str = "default") -> dict[str, Any]:
        session = self._get_session(session_id)
        if not session.hand:
            self._draw_cards(session, session.opening_hand_size)
            return {
                "session_id": session_id,
                "mulliganed": False,
                "note": "No existing hand found, so an opening hand was drawn instead.",
                "state": session.snapshot(),
            }

        session.library.extend(session.hand)
        session.hand.clear()
        random.shuffle(session.library)
        session.mulligans_taken += 1
        redrawn = self._draw_cards(session, session.opening_hand_size)
        return {
            "session_id": session_id,
            "mulliganed": True,
            "drawn": [summarize_for_zone(card) for card in redrawn],
            "state": session.snapshot(),
        }

    def sideboard(
        self,
        *,
        session_id: str = "default",
        swaps: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        session = self._get_session(session_id)
        if session.deck.format_name == TWIN_SUNS:
            raise ValueError("Twin Suns does not use a sideboard in this implementation.")
        if not swaps:
            raise ValueError("Provide at least one swap with 'out' and 'in' card names.")

        for swap in swaps:
            count = int(swap.get("count", 1))
            self._swap_cards(session.deck.main_deck, session.deck.sideboard, str(swap["out"]), count)
            self._swap_cards(session.deck.sideboard, session.deck.main_deck, str(swap["in"]), count)

        validation = self.validate_parsed_deck(session.deck)
        self.sessions[session_id] = self._build_session(session_id=session_id, deck=session.deck, shuffle=True)
        self.sessions[session_id].notes.append("Playtest zones were reset after sideboarding.")
        return {
            "session_id": session_id,
            "validation": validation,
            "deck_summary": summarize_deck(session.deck),
            "state": self.sessions[session_id].snapshot(),
        }

    def resource_phase(
        self,
        *,
        session_id: str = "default",
        resource_card: str | None = None,
        draw_for_turn: bool = True,
    ) -> dict[str, Any]:
        session = self._get_session(session_id)
        for card in session.resources:
            card.ready = True

        resource_added: dict[str, Any] | None = None
        if resource_card:
            hand_index = find_card_index(session.hand, session.card_index, resource_card)
            lookup_id = session.hand.pop(hand_index)
            card = session.card_index[lookup_id]
            resource_state = GameCardState(
                instance_id=session.next_instance_id("resource"),
                lookup_id=lookup_id,
                name=str(card["display_name"]),
                zone="resource",
                ready=False,
                deployed=True,
            )
            session.resources.append(resource_state)
            resource_added = summarize_game_card(resource_state, session.card_index)

        drawn_cards: list[dict[str, Any]] = []
        if draw_for_turn:
            drawn_cards = [summarize_for_zone(card) for card in self._draw_cards(session, 1)]

        return {
            "session_id": session_id,
            "resource_added": resource_added,
            "drawn": drawn_cards,
            "state": session.snapshot(),
        }

    def regroup_phase(self, *, session_id: str = "default") -> None:
        """Ready all cards for the active player (called at start of turn, separate from resource phase)."""
        session = self._get_session(session_id)
        for card in session.resources + session.ground_arena + session.space_arena + session.leaders + session.bases:
            card.ready = True

    def play_card(
        self,
        *,
        session_id: str = "default",
        card_name: str,
        source_zone: str = "hand",
        destination: str = "ground",
        ready: bool = True,
        damage: int = 0,
        experience: int = 0,
        shield: int = 0,
    ) -> dict[str, Any]:
        session = self._get_session(session_id)
        normalized_source = normalize_zone(source_zone)
        normalized_destination = normalize_zone(destination)

        if normalized_source in {"ground", "space", "resource", "leader", "base"}:
            moved_state = self._move_existing_state(
                session=session,
                card_name=card_name,
                source_zone=normalized_source,
                destination=normalized_destination,
                ready=ready,
                damage=damage,
                experience=experience,
                shield=shield,
            )
            return {
                "session_id": session_id,
                "played": summarize_game_card(moved_state, session.card_index),
                "state": session.snapshot(),
            }

        if normalized_source not in {"hand", "discard"}:
            raise ValueError(f"Unsupported source zone for play_card: {source_zone}")

        if normalized_source == "hand":
            zone = session.hand
        else:
            zone = session.discard

        zone_index = find_card_index(zone, session.card_index, card_name)
        lookup_id = zone.pop(zone_index)
        raw_card = session.card_index[lookup_id]
        card_state = GameCardState(
            instance_id=session.next_instance_id("board"),
            lookup_id=lookup_id,
            name=str(raw_card["display_name"]),
            zone=normalized_destination,
            ready=ready,
            damage=max(0, damage),
            experience=max(0, experience),
            shield=max(0, shield),
            arena=normalized_destination if normalized_destination in {"ground", "space"} else None,
            deployed=True,
        )
        self._append_state_to_zone(session, card_state, normalized_destination)
        return {
            "session_id": session_id,
            "played": summarize_game_card(card_state, session.card_index),
            "state": session.snapshot(),
        }

    def move_card(
        self,
        *,
        session_id: str = "default",
        card_name: str,
        source_zone: str,
        destination: str,
        ready: bool | None = None,
    ) -> dict[str, Any]:
        session = self._get_session(session_id)
        moved_state = self._move_existing_state(
            session=session,
            card_name=card_name,
            source_zone=normalize_zone(source_zone),
            destination=normalize_zone(destination),
            ready=ready,
        )
        return {
            "session_id": session_id,
            "moved": summarize_game_card(moved_state, session.card_index),
            "state": session.snapshot(),
        }

    def set_card_state(
        self,
        *,
        session_id: str = "default",
        card_name: str,
        zone: str,
        ready: bool | None = None,
        damage: int | None = None,
        experience: int | None = None,
        shield: int | None = None,
    ) -> dict[str, Any]:
        session = self._get_session(session_id)
        card_state = self._find_game_card(session, card_name=card_name, zone=normalize_zone(zone))
        if ready is not None:
            card_state.ready = ready
        if damage is not None:
            card_state.damage = max(0, damage)
        if experience is not None:
            card_state.experience = max(0, experience)
        if shield is not None:
            card_state.shield = max(0, shield)
        return {
            "session_id": session_id,
            "updated": summarize_game_card(card_state, session.card_index),
            "state": session.snapshot(),
        }

    def defeat_card(
        self,
        *,
        session_id: str = "default",
        card_name: str,
        zone: str,
    ) -> dict[str, Any]:
        session = self._get_session(session_id)
        moved_state = self._move_existing_state(
            session=session,
            card_name=card_name,
            source_zone=normalize_zone(zone),
            destination="discard",
            ready=False,
        )
        return {
            "session_id": session_id,
            "defeated": summarize_game_card(moved_state, session.card_index),
            "state": session.snapshot(),
        }

    def validate_deck(
        self,
        *,
        session_id: str | None = None,
        decklist: str | dict[str, Any] | None = None,
        format_name: str = PREMIER,
    ) -> dict[str, Any]:
        parsed = self._resolve_deck_input(session_id=session_id, decklist=decklist, format_name=format_name)
        return self.validate_parsed_deck(parsed)

    def analyze_deck(
        self,
        *,
        session_id: str | None = None,
        decklist: str | dict[str, Any] | None = None,
        format_name: str = PREMIER,
        target_matchups: list[str] | None = None,
        meta_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        parsed = self._resolve_deck_input(session_id=session_id, decklist=decklist, format_name=format_name)
        validation = self.validate_parsed_deck(parsed)

        main_cards = expand_entries(parsed.main_deck)
        costs = [parse_int(card.get("cost")) for card in main_cards if parse_int(card.get("cost")) is not None]
        type_counts = Counter(str(card.get("card_type", "Unknown")) for card in main_cards)
        aspect_counts = Counter(aspect for card in main_cards for aspect in card.get("aspects", []))
        keyword_counts = Counter(keyword for card in main_cards for keyword in card.get("keywords", []))
        trait_counts = Counter(trait for card in main_cards for trait in card.get("traits", []))
        curve = Counter(bucket_cost(parse_int(card.get("cost"))) for card in main_cards)
        role_counts = Counter(role for card in main_cards for role in detect_roles(card))
        off_aspect_cards = validation["aspect_penalties"]["cards"]
        off_aspect_slots = sum(item["quantity"] for item in off_aspect_cards)
        unit_count = type_counts.get("Unit", 0)
        early_curve = sum(1 for cost in costs if cost is not None and cost <= 2)

        synergy_score = 50
        if validation["legal"]:
            synergy_score += 10
        if off_aspect_slots <= 3:
            synergy_score += 10
        else:
            synergy_score -= min(20, off_aspect_slots * 2)
        if 8 <= early_curve <= 20:
            synergy_score += 8
        if unit_count >= 18:
            synergy_score += 8
        if max(trait_counts.values(), default=0) >= 8:
            synergy_score += 7
        if max(keyword_counts.values(), default=0) >= 5:
            synergy_score += 7
        if costs and mean(costs) > 4.5:
            synergy_score -= 10

        available_aspects = collect_deck_aspects(parsed)
        leaders = [entry.display_name for entry in parsed.leaders]
        base = parsed.bases[0].display_name if parsed.bases else None
        style_notes = build_style_notes(type_counts=type_counts, role_counts=role_counts, curve=curve)
        meta_summary = normalize_meta_context(target_matchups=target_matchups, meta_context=meta_context)
        matchup_scores = evaluate_matchups(
            main_cards=main_cards,
            role_counts=role_counts,
            keyword_counts=keyword_counts,
            early_curve=early_curve,
            meta_summary=meta_summary,
        )

        # Real interaction density — uses the same scoring model the picker
        # optimizes for. avg_per_card is comparable across decks; tribal
        # builds (e.g. Vehicle/Pilot) score 50+, goodstuff piles 10–30.
        # See `interaction_glossary.py` for the provides/needs model.
        all_resolved = [entry.card for entry in parsed.leaders + parsed.bases + parsed.main_deck if entry.card]
        aspect_pool_now = {f"aspect:{a}" for c in all_resolved for a in (c.get("aspects") or [])}
        interaction_per_card: list[float] = []
        for entry in parsed.main_deck:
            c = entry.card
            if not c:
                continue
            cand_p = interaction_provides_set(c)
            cand_n = _filter_aspect_needs(interaction_needs_set(c, score_aspects=True), aspect_pool_now)
            cand_t = {t for t in cand_p if t.startswith("trait:")}
            score = 0.0
            for other in all_resolved:
                if other is c:
                    continue
                op = interaction_provides_set(other)
                on = _filter_aspect_needs(interaction_needs_set(other, score_aspects=True), aspect_pool_now)
                ot = {t for t in op if t.startswith("trait:")}
                score += INTERACTION_PAYOFF_W * min(len(on & cand_p), INTERACTION_CAP_PER_PAIR)
                score += INTERACTION_ENABLER_W * min(len(cand_n & op), INTERACTION_CAP_PER_PAIR)
                score += INTERACTION_TRAIT_W * min(len(cand_t & ot), INTERACTION_CAP_PER_PAIR)
            interaction_per_card.append(score)
        interaction_density = (
            round(sum(interaction_per_card) / len(interaction_per_card), 1)
            if interaction_per_card
            else 0.0
        )
        # Per-pair normalized — division by (deck_size - 1) makes the metric
        # comparable across formats. Premier and Twin Suns both end up in
        # the ~0.5 (goodstuff) to ~4.5 (tribal) range.
        deck_pair_count = max(len(all_resolved) - 1, 1)
        interaction_per_pair = round(interaction_density / deck_pair_count, 2)

        return {
            "format": parsed.format_name,
            "leaders": leaders,
            "base": base,
            "validation": validation,
            "deck_size": len(main_cards),
            "average_cost": round(mean(costs), 2) if costs else None,
            "resource_curve": dict(sorted(curve.items())),
            "type_breakdown": dict(sorted(type_counts.items())),
            "aspect_breakdown": dict(sorted(aspect_counts.items())),
            "keyword_breakdown": dict(keyword_counts.most_common(10)),
            "trait_breakdown": dict(trait_counts.most_common(10)),
            "role_breakdown": dict(role_counts.most_common()),
            "available_aspects": sorted(available_aspects),
            "synergy_score": max(0, min(100, synergy_score)),
            "interaction_density": interaction_density,
            "interaction_per_pair": interaction_per_pair,
            "style_notes": style_notes,
            "meta_summary": meta_summary,
            "matchup_scores": matchup_scores,
        }

    def suggest_cards(
        self,
        *,
        goal: str,
        session_id: str | None = None,
        decklist: str | dict[str, Any] | None = None,
        format_name: str = PREMIER,
        limit: int = 8,
        target_matchups: list[str] | None = None,
        meta_context: dict[str, Any] | None = None,
        only_owned: bool = False,
    ) -> dict[str, Any]:
        parsed = self._resolve_deck_input(session_id=session_id, decklist=decklist, format_name=format_name)
        analysis = self.analyze_deck(
            session_id=session_id,
            decklist=decklist,
            format_name=format_name,
            target_matchups=target_matchups,
            meta_context=meta_context,
        )
        available_aspects = collect_deck_aspects(parsed)
        existing_counts = entry_quantity_by_name(parsed.main_deck + parsed.sideboard)
        early_curve_gap = max(0, 12 - quantity_for_cost(parsed.main_deck, 0, 2))
        goal_query = compile_goal_query(goal)
        candidate_pool = self._candidate_cards(goal_query=goal_query, available_aspects=available_aspects, only_owned=only_owned)
        meta_summary = normalize_meta_context(target_matchups=target_matchups, meta_context=meta_context)

        scored: list[tuple[float, dict[str, Any], list[str]]] = []
        collection_active = only_owned and self.collection_service is not None
        for candidate in candidate_pool:
            name = str(candidate["display_name"])
            card_type = str(candidate.get("card_type", ""))
            if card_type in {"Leader", "Base"}:
                continue
            if collection_active and not self._candidate_is_owned(candidate):
                continue

            existing_quantity = existing_counts.get(name, 0)
            if parsed.format_name == TWIN_SUNS and existing_quantity >= 1:
                continue
            if parsed.format_name == PREMIER and existing_quantity >= PREMIER_COPY_LIMIT:
                continue

            score = 0.0
            reasons: list[str] = []
            missing_aspects = sorted(set(candidate.get("aspects", [])) - available_aspects)
            if missing_aspects:
                score -= len(missing_aspects) * 20
                reasons.append(f"Costs +{len(missing_aspects) * ASPECT_PENALTY_PER_MISSING_ICON} resources off-aspect.")
            else:
                score += 18
                reasons.append("Fully on-plan with your current leader/base aspect pool.")

            goal_tokens = tokenize_text(goal_query)
            searchable_text = " ".join(
                [
                    str(candidate.get("display_name", "")),
                    str(candidate.get("front_text", "")),
                    " ".join(candidate.get("traits", [])),
                    " ".join(candidate.get("keywords", [])),
                ]
            ).lower()
            matched_tokens = [token for token in goal_tokens if token in searchable_text]
            if matched_tokens:
                score += 10 + len(matched_tokens) * 2
                reasons.append(f"Matches the goal language: {', '.join(sorted(set(matched_tokens)))}.")

            cost = parse_int(candidate.get("cost"))
            if early_curve_gap and cost is not None and cost <= 2:
                score += 8
                reasons.append("Helps patch an early-game curve gap.")
            if analysis["type_breakdown"].get("Event", 0) < 10 and card_type == "Event":
                score += 4
                reasons.append("Adds a bit more stack interaction and trick density.")
            if analysis["type_breakdown"].get("Unit", 0) < 18 and card_type == "Unit":
                score += 4
                reasons.append("Adds to your board presence count.")

            shared_traits = set(candidate.get("traits", [])) & set(analysis["trait_breakdown"].keys())
            if shared_traits:
                score += min(6, len(shared_traits) * 2)
                reasons.append(f"Supports existing tribal hooks: {', '.join(sorted(shared_traits))}.")

            shared_keywords = set(candidate.get("keywords", [])) & set(analysis["keyword_breakdown"].keys())
            if shared_keywords:
                score += min(4, len(shared_keywords) * 2)
                reasons.append(f"Reinforces current keyword themes: {', '.join(sorted(shared_keywords))}.")

            matchup_score, matchup_reasons = score_candidate_for_matchups(candidate=candidate, meta_summary=meta_summary)
            if matchup_score:
                score += matchup_score
                reasons.extend(matchup_reasons[:2])

            scored.append((score, candidate, reasons))

        top_hits = sorted(scored, key=lambda item: item[0], reverse=True)[: max(1, min(limit, 12))]
        if not top_hits:
            fallback_pool = self._candidate_cards(goal_query="unit event", available_aspects=available_aspects, only_owned=only_owned)
            for candidate in fallback_pool:
                name = str(candidate["display_name"])
                if collection_active and not self._candidate_is_owned(candidate):
                    continue
                existing_quantity = existing_counts.get(name, 0)
                if parsed.format_name == TWIN_SUNS and existing_quantity >= 1:
                    continue
                if parsed.format_name == PREMIER and existing_quantity >= PREMIER_COPY_LIMIT:
                    continue
                top_hits.append(
                    (
                        0.0,
                        candidate,
                        ["Safe fallback option from your aspect pool while the goal-specific search came up empty."],
                    )
                )
                if len(top_hits) >= max(1, min(limit, 12)):
                    break
        return {
            "goal": goal,
            "format": parsed.format_name,
            "leaders": [entry.display_name for entry in parsed.leaders],
            "base": parsed.bases[0].display_name if parsed.bases else None,
            "meta_summary": meta_summary,
            "suggestions": [
                {
                    "score": round(score, 2),
                    "card": summarize_for_zone(candidate),
                    "reasons": reasons[:3],
                }
                for score, candidate, reasons in top_hits
            ],
        }

    def generate_deck(
        self,
        *,
        theme: str,
        format_name: str = PREMIER,
        primary_aspects: list[str] | None = None,
        leader_names: list[str] | None = None,
        base_name: str | None = None,
        budget: str | None = None,
        target_matchups: list[str] | None = None,
        meta_context: dict[str, Any] | None = None,
        only_owned: bool = False,
    ) -> dict[str, Any]:
        self.card_service._ensure_local_catalog()
        normalized_format = normalize_format(format_name)
        meta_summary = normalize_meta_context(target_matchups=target_matchups, meta_context=meta_context)
        leaders = self._pick_leaders(
            theme=theme,
            format_name=normalized_format,
            leader_names=leader_names,
            only_owned=only_owned,
        )
        aspect_pool = set(primary_aspects or [])
        for leader in leaders:
            aspect_pool.update(leader.get("aspects", []))

        base = self._pick_base(base_name=base_name, aspect_pool=aspect_pool, only_owned=only_owned)
        aspect_pool.update(base.get("aspects", []))

        target_main_size = PREMIER_MAIN_DECK_MIN if normalized_format == PREMIER else TWIN_SUNS_MAIN_DECK_MIN
        candidate_pool = self._candidate_cards(goal_query=compile_goal_query(theme), available_aspects=aspect_pool, only_owned=only_owned)
        filler_pool = self._candidate_cards(goal_query="unit event", available_aspects=aspect_pool, only_owned=only_owned)
        merged_by_id: dict[str, dict[str, Any]] = {}
        for candidate in list(candidate_pool) + list(filler_pool):
            key = str(candidate.get("lookup_id") or f"{candidate.get('set_code')}-{candidate.get('number')}")
            merged_by_id.setdefault(key, candidate)
        pool = list(merged_by_id.values())

        main_cards: list[DeckCardEntry] = []
        # Track copies per canonical lookup_id (SET/NNN) — not per display_name —
        # so near-duplicate printings ("Prepare For Takeoff" / "Prepare for Takeoff")
        # don't slip through as distinct cards.
        id_counts: Counter[str] = Counter()
        copy_limit = 1 if normalized_format == TWIN_SUNS else PREMIER_COPY_LIMIT
        collection_active = only_owned and self.collection_service is not None

        def card_key(card: dict[str, Any]) -> str:
            # Canonical card identity. The same card can have many printings
            # (Normal / Hyperspace / Foil / Hyperspace Foil) with distinct
            # lookup_ids — dedup on (Name, Subtitle) so all printings collapse
            # to one card. Lowercased to also catch case-mismatched catalog
            # rows ("Prepare For Takeoff" vs "Prepare for Takeoff").
            name = (card.get("name") or card.get("display_name") or "").strip().lower()
            # display_name sometimes already includes " - Subtitle"; strip it
            # then add subtitle separately so the key is normalized.
            if " - " in name:
                name = name.split(" - ", 1)[0].strip()
            subtitle = (card.get("subtitle") or "").strip().lower()
            if name:
                return f"name:{name}|{subtitle}"
            lid = card.get("lookup_id")
            if lid:
                return str(lid)
            return f"{card.get('set_code')}/{card.get('number')}"

        TYPE_TARGET_FRACTIONS = {"Unit": 0.78, "Event": 0.17, "Upgrade": 0.05}
        type_targets = {
            ctype: max(1, int(round(target_main_size * frac)))
            for ctype, frac in TYPE_TARGET_FRACTIONS.items()
        }
        type_counts: Counter[str] = Counter()

        base_scores: dict[int, float] = {}
        for candidate in pool:
            base_scores[id(candidate)] = generation_score(
                card=candidate,
                theme=theme,
                aspect_pool=aspect_pool,
                budget=budget,
                meta_summary=meta_summary,
                format_name=normalized_format,
            )

        # Cache provides/needs/traits sets for every card we may score against.
        interaction_cache: dict[int, tuple[set[str], set[str], set[str]]] = {}

        def get_interaction_sets(card: dict[str, Any]) -> tuple[set[str], set[str], set[str]]:
            key = id(card)
            cached = interaction_cache.get(key)
            if cached is not None:
                return cached
            provides = interaction_provides_set(card)
            needs = interaction_needs_set(card, score_aspects=True)
            traits = {t for t in provides if t.startswith("trait:")}
            interaction_cache[key] = (provides, needs, traits)
            return interaction_cache[key]

        # Anchors (leaders + base) seed the deck-context for the very first pick.
        deck_so_far: list[dict[str, Any]] = list(leaders) + [base]
        for anchor in deck_so_far:
            get_interaction_sets(anchor)

        # Combo-package context: pre-tag every card we might pick + the anchors,
        # then score candidates by how much they reinforce a package the deck
        # is already building toward.
        from .combo_packages import tag_card as _tag_card
        combo_tag_cache: dict[int, dict[str, list[str]]] = {}
        def _tags_for(card: dict[str, Any]) -> dict[str, list[str]]:
            cached = combo_tag_cache.get(id(card))
            if cached is not None:
                return cached
            tags = _tag_card(card)
            combo_tag_cache[id(card)] = tags
            return tags
        for anchor in deck_so_far:
            _tags_for(anchor)

        # Running per-package support count from the current deck.
        package_support: Counter[str] = Counter()
        for anchor in deck_so_far:
            tags = _tags_for(anchor)
            for p in tags["enables"]:
                package_support[p] += 1
            for p in tags["pays_off"]:
                package_support[p] += 1

        COMBO_ACTIVE_THRESHOLD = 2     # at least N supporters → +2 per pkg
        COMBO_STRONG_THRESHOLD = 5     # at least N supporters → +3 per pkg
        COMBO_BONUS_CAP = 6.0          # max combo bonus per candidate

        def combo_term(candidate: dict[str, Any]) -> float:
            tags = _tags_for(candidate)
            cand_pkgs = set(tags["enables"]) | set(tags["pays_off"])
            if not cand_pkgs:
                return 0.0
            total = 0.0
            for pkg in cand_pkgs:
                support = package_support[pkg]
                if support >= COMBO_STRONG_THRESHOLD:
                    total += 3.0
                elif support >= COMBO_ACTIVE_THRESHOLD:
                    total += 2.0
                # else: package has no foothold yet — no bonus
            return min(total, COMBO_BONUS_CAP)

        def record_combo_pick(card: dict[str, Any]) -> None:
            tags = _tags_for(card)
            for p in tags["enables"]:
                package_support[p] += 1
            for p in tags["pays_off"]:
                package_support[p] += 1

        def deck_aspect_pool() -> set[str]:
            return {
                f"aspect:{a}"
                for d in deck_so_far
                for a in (d.get("aspects") or [])
            }

        def interaction_term(candidate: dict[str, Any], aspect_pool_now: set[str]) -> float:
            cand_provides, cand_needs, cand_traits = get_interaction_sets(candidate)
            cand_needs_filtered = _filter_aspect_needs(cand_needs, aspect_pool_now)
            total = 0.0
            for d in deck_so_far:
                d_provides, d_needs, d_traits = get_interaction_sets(d)
                d_needs_filtered = _filter_aspect_needs(d_needs, aspect_pool_now)
                total += INTERACTION_PAYOFF_W * min(
                    len(d_needs_filtered & cand_provides), INTERACTION_CAP_PER_PAIR
                )
                total += INTERACTION_ENABLER_W * min(
                    len(cand_needs_filtered & d_provides), INTERACTION_CAP_PER_PAIR
                )
                total += INTERACTION_TRAIT_W * min(
                    len(cand_traits & d_traits), INTERACTION_CAP_PER_PAIR
                )
            return total

        def eligible(candidate: dict[str, Any]) -> bool:
            if str(candidate.get("card_type")) in {"Leader", "Base"}:
                return False
            if id_counts[card_key(candidate)] >= copy_limit:
                return False
            if collection_active and not self._candidate_is_owned(candidate):
                return False
            return True

        # Soft curve penalty: once running average cost exceeds target, penalise
        # any candidate above the running average proportionally to overshoot.
        target_avg_cost = (
            TARGET_AVG_COST_TWIN_SUNS
            if normalized_format == TWIN_SUNS
            else TARGET_AVG_COST_PREMIER
        )
        def cost_overrun_penalty(candidate: dict[str, Any]) -> float:
            picked_costs = [parse_int((d.get("cost") or d.get("Cost"))) or 0 for d in deck_so_far if d.get("card_type") == "Unit"]
            if not picked_costs:
                return 0.0
            avg_now = sum(picked_costs) / len(picked_costs)
            if avg_now <= target_avg_cost:
                return 0.0
            cand_cost = parse_int(candidate.get("cost")) or 0
            if cand_cost <= avg_now:
                return 0.0
            return COST_OVERRUN_W * (cand_cost - avg_now)

        # Section-based budget: pick top N per type. Allocate slots so they sum
        # to target_main_size exactly; spill rounding into Units (largest slot).
        section_quotas = {
            ctype: int(round(target_main_size * frac))
            for ctype, frac in TYPE_TARGET_FRACTIONS.items()
        }
        slot_diff = target_main_size - sum(section_quotas.values())
        section_quotas["Unit"] += slot_diff

        # Run a separate greedy pass per type. deck_so_far accumulates across
        # sections so cross-type interaction (e.g. an event that pays off
        # already-picked units) is still scored.
        section_order = ["Unit", "Event", "Upgrade"]
        for section_type in section_order:
            quota = section_quotas[section_type]
            if quota <= 0:
                continue
            section_pool = [
                c for c in pool
                if str(c.get("card_type")) == section_type and eligible(c)
            ]
            picked_in_section = 0
            while picked_in_section < quota and section_pool:
                aspect_pool_now = deck_aspect_pool()
                best = None
                best_score = float("-inf")
                best_idx = -1
                for idx, candidate in enumerate(section_pool):
                    score = (
                        base_scores.get(id(candidate), 0.0)
                        + INTERACTION_WEIGHT * interaction_term(candidate, aspect_pool_now)
                        + cost_overrun_penalty(candidate)
                        + combo_term(candidate)
                    )
                    if score > best_score:
                        best_score = score
                        best = candidate
                        best_idx = idx
                if best is None:
                    break
                section_pool.pop(best_idx)
                deck_so_far.append(best)
                record_combo_pick(best)

                display_name = str(best["display_name"])
                key = card_key(best)
                # Honor per-card "up to N copies" overrides (Swarming Vulture
                # Droid, Battle Droid swarm, etc) — singleton format still lets
                # these go to multiple copies.
                override = card_copy_override(best)
                if normalized_format == TWIN_SUNS:
                    quantity = override if override and override > 1 else 1
                else:
                    quantity = recommended_quantity(best)
                effective_limit = max(copy_limit, override) if override else copy_limit
                quantity = min(quantity, effective_limit - id_counts[key])
                if collection_active:
                    quantity = min(quantity, self._candidate_owned_count(best))
                remaining_slots = quota - picked_in_section
                quantity = min(quantity, remaining_slots)
                if quantity <= 0:
                    continue
                main_cards.append(
                    DeckCardEntry(
                        quantity=quantity,
                        name=display_name,
                        zone="main_deck",
                        set_code=str(best["set_code"]),
                        card_number=str(best["number"]),
                        card=best,
                    )
                )
                id_counts[key] += quantity
                type_counts[section_type] += quantity
                picked_in_section += quantity

        # Backfill: if any section under-quota'd (e.g. tiny owned pool),
        # grab top-scoring eligible cards regardless of type to hit deck size.
        current_total = sum(entry.quantity for entry in main_cards)
        if current_total < target_main_size:
            backfill_pool = [c for c in pool if eligible(c)]
            while current_total < target_main_size and backfill_pool:
                aspect_pool_now = deck_aspect_pool()
                best = None
                best_score = float("-inf")
                best_idx = -1
                for idx, candidate in enumerate(backfill_pool):
                    score = (
                        base_scores.get(id(candidate), 0.0)
                        + INTERACTION_WEIGHT * interaction_term(candidate, aspect_pool_now)
                        + combo_term(candidate)
                    )
                    if score > best_score:
                        best_score = score
                        best = candidate
                        best_idx = idx
                if best is None:
                    break
                backfill_pool.pop(best_idx)
                deck_so_far.append(best)
                record_combo_pick(best)
                display_name = str(best["display_name"])
                key = card_key(best)
                override = card_copy_override(best)
                if normalized_format == TWIN_SUNS:
                    quantity = override if override and override > 1 else 1
                else:
                    quantity = recommended_quantity(best)
                effective_limit = max(copy_limit, override) if override else copy_limit
                quantity = min(quantity, effective_limit - id_counts[key])
                if collection_active:
                    quantity = min(quantity, self._candidate_owned_count(best))
                quantity = min(quantity, target_main_size - current_total)
                if quantity <= 0:
                    continue
                main_cards.append(
                    DeckCardEntry(
                        quantity=quantity,
                        name=display_name,
                        zone="main_deck",
                        set_code=str(best["set_code"]),
                        card_number=str(best["number"]),
                        card=best,
                    )
                )
                id_counts[key] += quantity
                type_counts[str(best.get("card_type", "Unit"))] += quantity
                current_total += quantity

        parsed = ParsedDeck(
            format_name=normalized_format,
            leaders=[
                DeckCardEntry(
                    quantity=1,
                    name=str(leader["display_name"]),
                    zone="leaders",
                    set_code=str(leader["set_code"]),
                    card_number=str(leader["number"]),
                    card=leader,
                )
                for leader in leaders
            ],
            bases=[
                DeckCardEntry(
                    quantity=1,
                    name=str(base["display_name"]),
                    zone="bases",
                    set_code=str(base["set_code"]),
                    card_number=str(base["number"]),
                    card=base,
                )
            ],
            main_deck=trim_to_size(main_cards, target_main_size),
            sideboard=[],
            title=f"{theme.title()} {normalized_format.replace('_', ' ').title()} Brew",
        )

        validation = self.validate_parsed_deck(parsed)
        analysis = self.analyze_deck(
            decklist=self.export_deck(deck=parsed, export_format="json")["deck"],
            format_name=normalized_format,
            target_matchups=target_matchups,
            meta_context=meta_context,
        )
        return {
            "theme": theme,
            "format": normalized_format,
            "budget": budget,
            "meta_summary": meta_summary,
            "deck": self.export_deck(deck=parsed, export_format="plain_text")["deck"],
            "deck_holoscan": self.export_deck(deck=parsed, export_format="holoscan")["deck"],
            "validation": validation,
            "analysis": analysis,
            "notes": [
                "This first-pass generator prioritizes on-aspect cards, early curve stability, and cards that match the requested theme language.",
                "You can improve it further by uploading the generated list and using swu_suggest_cards with matchup-specific goals.",
            ],
        }

    def rank_leader_pairs(
        self,
        *,
        theme: str = "",
        format_name: str = TWIN_SUNS,
        primary_aspects: list[str] | None = None,
        moral: str | None = None,
        only_owned: bool = True,
        top_k: int = 5,
        base_name: str | None = None,
        include_decks: bool = False,
    ) -> dict[str, Any]:
        """Brew a deck for every legal leader pairing and rank them.

        Twin Suns requires the two leaders to share Heroism or Villainy. This
        method enumerates all such pairs from the (optionally owned) leader
        pool, runs `generate_deck` for each, and returns the top_k ranked by
        a composite score: synergy + interaction density - off-aspect burden.

        moral: restrict to "Heroism" or "Villainy" pairs (default: both).
        primary_aspects: filter leaders whose aspects intersect this set.
        """
        normalized_format = normalize_format(format_name)
        if normalized_format != TWIN_SUNS:
            raise ValueError(
                "Leader-pair ranking is only meaningful for Twin Suns format."
            )

        # Build the candidate leader pool. Two paths:
        # - only_owned=True: walk the collection directly. The API search
        #   has a hard 100-result cap that silently excludes some leaders
        #   (Qui-Gon Jinn, Obi-Wan Kenobi found missing in testing). Going
        #   through the collection is more reliable when we already know
        #   the user owns the cards.
        # - only_owned=False: fall back to the API search.
        self.card_service._ensure_local_catalog()
        leaders: list[dict[str, Any]] = []
        if only_owned and self.collection_service is not None:
            # Iterate every owned entry and filter to leaders via card lookup.
            self.collection_service._load_from_disk()
            for entry in self.collection_service._entries.values():
                # Cheap filter using collection metadata if present.
                # If type isn't on the entry yet, lookup_card will tell us.
                try:
                    detail = self.card_service.lookup_card(
                        set_code=entry.set_code,
                        card_number=entry.card_number,
                    )
                except Exception:
                    continue
                if detail.get("card_type") == "Leader":
                    leaders.append(detail)
        else:
            try:
                result = self.card_service.search_cards(
                    query="*", filters={"type": "Leader"}, limit=200
                )
            except Exception:
                result = {"cards": []}
            for card in result.get("cards", []):
                looked_up = self._safe_lookup(card)
                if looked_up is not None and looked_up.get("card_type") == "Leader":
                    leaders.append(looked_up)

        # Dedup by lookup_id and treat alt-art reprints (same name+subtitle)
        # as the same leader so we don't pair a printing with itself.
        seen_ids: set[str] = set()
        seen_idents: set[tuple[str, str]] = set()
        deduped: list[dict[str, Any]] = []
        for leader in leaders:
            lid = str(leader.get("lookup_id") or "")
            if lid in seen_ids:
                continue
            seen_ids.add(lid)
            ident = (
                str(leader.get("name", "")).strip().lower(),
                str(leader.get("subtitle", "") or "").strip().lower(),
            )
            if ident in seen_idents:
                continue
            seen_idents.add(ident)
            deduped.append(leader)
        leaders = deduped

        if only_owned and self.collection_service is not None:
            leaders = [
                leader for leader in leaders if self._candidate_is_owned(leader)
            ]

        if primary_aspects:
            wanted = set(primary_aspects)
            leaders = [
                leader for leader in leaders
                if set(leader.get("aspects") or []) & wanted
            ]

        if moral:
            normalized_moral = moral.strip().capitalize()
            leaders = [
                leader for leader in leaders
                if normalized_moral in (leader.get("aspects") or [])
            ]

        # Enumerate unique unordered pairs that share Heroism or Villainy.
        pairs: list[tuple[dict, dict, str]] = []
        for i, first in enumerate(leaders):
            asps_a = set(first.get("aspects") or [])
            for second in leaders[i + 1:]:
                asps_b = set(second.get("aspects") or [])
                shared_morals = asps_a & asps_b & {"Heroism", "Villainy"}
                if not shared_morals:
                    continue
                pairs.append((first, second, sorted(shared_morals)[0]))

        if not pairs:
            return {
                "format": normalized_format,
                "theme": theme,
                "moral_filter": moral,
                "leader_pool_size": len(leaders),
                "pairs_considered": 0,
                "ranked": [],
                "note": "No valid pairs found. Loosen filters or add owned=False.",
            }

        # Theme parsing — extract which combo packages this brew should
        # express. If the theme mentions "force"/"jedi", we'll bonus decks
        # heavy in force_engine-tagged cards, etc.
        theme_lower = (theme or "").lower()
        target_packages: set[str] = set()
        for keyword, pkgs in THEME_TO_PACKAGES.items():
            if keyword in theme_lower:
                target_packages |= pkgs

        def _leader_text(leader: dict[str, Any]) -> str:
            return " ".join(
                str(leader.get(k) or "") for k in
                ("front_text", "back_text", "epic_action")
            )

        def _leader_roles(leader: dict[str, Any]) -> dict[str, set[str]]:
            text = _leader_text(leader)
            roles_per_pkg: dict[str, set[str]] = {}
            for pkg, role_map in LEADER_PACKAGE_ROLES.items():
                roles: set[str] = set()
                for role_name, patterns in role_map.items():
                    for pat in patterns:
                        if re.search(pat, text, re.IGNORECASE):
                            roles.add(role_name)
                            break
                if roles:
                    roles_per_pkg[pkg] = roles
            return roles_per_pkg

        def _loop_bonus(first: dict, second: dict) -> tuple[float, dict[str, list[str]]]:
            if not target_packages:
                return 0.0, {}
            a_roles = _leader_roles(first)
            b_roles = _leader_roles(second)
            bonus = 0.0
            detail: dict[str, list[str]] = {}
            for pkg in target_packages:
                combined = a_roles.get(pkg, set()) | b_roles.get(pkg, set())
                if not combined:
                    continue
                if {"generator", "consumer"} <= combined:
                    bonus += LEADER_LOOP_CLOSED_BONUS
                    detail[pkg] = sorted(combined) + ["[closed-loop]"]
                elif {"generator", "payoff"} <= combined:
                    bonus += LEADER_LOOP_PAYOFF_BONUS
                    detail[pkg] = sorted(combined) + ["[gen+payoff]"]
                else:
                    bonus += LEADER_LOOP_TOUCH_BONUS
                    detail[pkg] = sorted(combined) + ["[touched]"]
            return bonus, detail

        # Brew + score each pair. Failures are logged but don't kill the run.
        from .combo_packages import tag_card as _tag_card_for_fit
        from .config import settings as _settings

        # Parse "<qty> <SET>/<NUM>" lines out of the holoscan main-deck section.
        _HOLOSCAN_LINE = re.compile(
            r"^\s*(\d+)\s+([A-Z][A-Z0-9]+)\s*/\s*(\d+)\s*$"
        )

        def _main_deck_from_holoscan(holoscan: str) -> list[tuple[str, str, int]]:
            entries: list[tuple[str, str, int]] = []
            in_main = False
            for raw in (holoscan or "").splitlines():
                stripped = raw.strip()
                if not stripped:
                    continue
                if stripped.lower().startswith("main deck"):
                    in_main = True
                    continue
                if stripped.lower().startswith(("leaders", "base", "sideboard")):
                    in_main = False
                    continue
                if not in_main:
                    continue
                match = _HOLOSCAN_LINE.match(stripped)
                if match:
                    qty, set_code, number = match.groups()
                    entries.append((set_code, number, int(qty)))
            return entries

        def _theme_fit(brew_result: dict[str, Any]) -> tuple[float, dict[str, int]]:
            """Count package-tagged cards in the deck against target packages.

            generate_deck doesn't include a structured deck_summary, so we
            parse the holoscan string back into (set, number, qty) tuples
            and look each card up from the cache to tag it.
            """
            if not target_packages:
                return 0.0, {}
            holoscan = brew_result.get("deck_holoscan", "")
            entries = _main_deck_from_holoscan(holoscan)
            if not entries:
                return 0.0, {}
            per_pkg: dict[str, int] = {p: 0 for p in target_packages}
            for set_code, number, qty in entries:
                cache_path = (
                    _settings.cache_dir
                    / f"{set_code.upper()}-{str(number).zfill(3)}.json"
                )
                if not cache_path.exists():
                    continue
                try:
                    card_data = json.loads(cache_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                tags = _tag_card_for_fit(card_data)
                hit_pkgs = (set(tags["enables"]) | set(tags["pays_off"])) & target_packages
                for p in hit_pkgs:
                    per_pkg[p] += qty
            total_hits = sum(per_pkg.values())
            bonus = min(total_hits * THEME_FIT_PER_MATCH, THEME_FIT_CAP)
            return bonus, per_pkg

        results: list[dict[str, Any]] = []
        for first, second, shared in pairs:
            pair_names = [str(first["display_name"]), str(second["display_name"])]
            try:
                brew = self.generate_deck(
                    theme=theme or "Twin Suns leader-pair brew",
                    format_name=normalized_format,
                    leader_names=pair_names,
                    base_name=base_name,
                    only_owned=only_owned,
                )
            except Exception as exc:
                results.append({
                    "leaders": pair_names,
                    "shared_moral": shared,
                    "error": str(exc),
                    "score": float("-inf"),
                })
                continue
            analysis = brew.get("analysis", {})
            validation = brew.get("validation", {})
            synergy = float(analysis.get("synergy_score") or 0)
            interaction = float(analysis.get("interaction_density") or 0)
            burden = float(
                validation.get("aspect_penalties", {}).get(
                    "total_extra_resource_burden", 0
                )
            )
            theme_bonus, package_hits = _theme_fit(brew)
            loop_bonus_val, loop_detail = _loop_bonus(first, second)
            score = (
                synergy
                + (interaction / 5.0)
                - (2.0 * burden)
                + theme_bonus
                + loop_bonus_val
            )
            entry: dict[str, Any] = {
                "leaders": pair_names,
                "shared_moral": shared,
                "base": (analysis.get("base") or brew.get("deck_summary", {}).get("bases", [None])[0]),
                "available_aspects": analysis.get("available_aspects"),
                "synergy_score": synergy,
                "interaction_density": interaction,
                "burden": burden,
                "theme_fit_bonus": round(theme_bonus, 2),
                "package_hits": package_hits,
                "leader_loop_bonus": round(loop_bonus_val, 2),
                "leader_loop_detail": loop_detail,
                "avg_cost": analysis.get("average_cost"),
                "deck_size": analysis.get("deck_size"),
                "trait_breakdown": analysis.get("trait_breakdown"),
                "role_breakdown": analysis.get("role_breakdown"),
                "score": round(score, 2),
            }
            if include_decks:
                entry["deck_holoscan"] = brew.get("deck_holoscan")
            results.append(entry)

        results.sort(key=lambda r: r.get("score", float("-inf")), reverse=True)
        return {
            "format": normalized_format,
            "theme": theme,
            "moral_filter": moral,
            "leader_pool_size": len(leaders),
            "pairs_considered": len(pairs),
            "target_packages": sorted(target_packages) or None,
            "ranked": results[:top_k],
            "scoring": (
                "score = synergy_score + interaction_density/5 "
                "- 2 × off_aspect_burden + theme_fit_bonus "
                "(0.5 per package-tagged card, capped at 25) "
                "+ leader_loop_bonus (+5 closed loop, +3 gen+payoff, "
                "+1 single touch — per target package)"
            ),
        }

    def export_deck(
        self,
        *,
        session_id: str | None = None,
        decklist: str | dict[str, Any] | None = None,
        format_name: str = PREMIER,
        export_format: str = "plain_text",
        deck: ParsedDeck | None = None,
    ) -> dict[str, Any]:
        parsed = deck or self._resolve_deck_input(session_id=session_id, decklist=decklist, format_name=format_name)
        normalized_format = export_format.strip().lower()
        if normalized_format == "json":
            return {
                "format": parsed.format_name,
                "deck": {
                    "title": parsed.title,
                    "leaders": [entry_to_export(entry) for entry in parsed.leaders],
                    "bases": [entry_to_export(entry) for entry in parsed.bases],
                    "main_deck": [entry_to_export(entry) for entry in parsed.main_deck],
                    "sideboard": [entry_to_export(entry) for entry in parsed.sideboard],
                },
            }

        # holoscan: emit `{qty} {SET}/{NNN}` per line — what the HoloScan
        # mobile app expects when importing decklists by set+number.
        # Title is intentionally omitted: it's not a parseable card entry and
        # would round-trip into the main deck as junk.
        if normalized_format in ("holoscan", "set_number"):
            def _id(entry: DeckCardEntry) -> str:
                num = str(entry.card_number or "").strip()
                if num.isdigit():
                    num = num.zfill(3)
                return f"{entry.set_code}/{num}"

            sections = []
            sections.append("Leaders")
            sections.extend(f"1 {_id(entry)}" for entry in parsed.leaders)
            sections.append("")
            sections.append("Base")
            sections.extend(f"1 {_id(entry)}" for entry in parsed.bases)
            sections.append("")
            sections.append("Main Deck")
            sections.extend(f"{entry.quantity} {_id(entry)}" for entry in parsed.main_deck)
            if parsed.sideboard:
                sections.append("")
                sections.append("Sideboard")
                sections.extend(f"{entry.quantity} {_id(entry)}" for entry in parsed.sideboard)
            return {
                "format": parsed.format_name,
                "export_format": normalized_format,
                "deck": "\n".join(sections).strip(),
            }

        sections = []
        if parsed.title:
            sections.append(parsed.title)
        sections.append("Leaders")
        sections.extend(f"1 {entry.display_name}" for entry in parsed.leaders)
        sections.append("")
        sections.append("Base")
        sections.extend(f"1 {entry.display_name}" for entry in parsed.bases)
        sections.append("")
        sections.append("Main Deck")
        sections.extend(f"{entry.quantity} {entry.display_name}" for entry in parsed.main_deck)
        if parsed.sideboard:
            sections.append("")
            sections.append("Sideboard")
            sections.extend(f"{entry.quantity} {entry.display_name}" for entry in parsed.sideboard)

        plain_text = "\n".join(sections).strip()
        return {
            "format": parsed.format_name,
            "export_format": normalized_format,
            "deck": plain_text,
        }

    def parse_decklist(self, *, decklist: str | dict[str, Any], format_name: str = PREMIER) -> ParsedDeck:
        normalized_format = normalize_format(format_name)
        if isinstance(decklist, dict):
            return self._parse_deck_dict(decklist, normalized_format)

        text = decklist.strip()
        if not text:
            raise ValueError("Decklist text is empty.")
        if text.startswith("{") or text.startswith("["):
            return self._parse_deck_dict(json.loads(text), normalized_format)

        current_section = "main_deck"
        parsed = ParsedDeck(format_name=normalized_format)
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            normalized_section = SECTION_ALIASES.get(line.rstrip(":").lower())
            if normalized_section:
                current_section = normalized_section
                continue

            entry = parse_deck_line(line, zone=current_section)
            if entry.zone == "leaders":
                parsed.leaders.append(entry)
            elif entry.zone == "bases":
                parsed.bases.append(entry)
            elif entry.zone == "sideboard":
                parsed.sideboard.append(entry)
            else:
                parsed.main_deck.append(entry)

        return parsed

    def resolve_deck(self, parsed: ParsedDeck) -> ParsedDeck:
        cache: dict[str, dict[str, Any]] = {}
        resolved = ParsedDeck(format_name=parsed.format_name, title=parsed.title)

        for zone_name in ("leaders", "bases", "main_deck", "sideboard"):
            zone_entries = getattr(parsed, zone_name)
            resolved_entries: list[DeckCardEntry] = []
            for entry in zone_entries:
                card = self._resolve_entry(entry, cache=cache)
                resolved_zone = zone_name
                if zone_name == "main_deck" and card["card_type"] == "Leader":
                    resolved_zone = "leaders"
                elif zone_name == "main_deck" and card["card_type"] == "Base":
                    resolved_zone = "bases"

                resolved_entries.append(
                    DeckCardEntry(
                        quantity=entry.quantity,
                        name=entry.name,
                        zone=resolved_zone,
                        set_code=str(card["set_code"]),
                        card_number=str(card["number"]),
                        card=card,
                    )
                )

            if zone_name == "leaders":
                resolved.leaders.extend(resolved_entries)
            elif zone_name == "bases":
                resolved.bases.extend(resolved_entries)
            elif zone_name == "main_deck":
                for entry in resolved_entries:
                    if entry.zone == "leaders":
                        resolved.leaders.append(entry)
                    elif entry.zone == "bases":
                        resolved.bases.append(entry)
                    else:
                        resolved.main_deck.append(entry)
            else:
                resolved.sideboard.extend(resolved_entries)

        return collapse_entries(resolved)

    def validate_parsed_deck(self, parsed: ParsedDeck) -> dict[str, Any]:
        deck = self.resolve_deck(parsed) if not all(entry.card for entry in parsed.main_deck + parsed.leaders + parsed.bases + parsed.sideboard) else parsed
        errors: list[str] = []
        warnings: list[str] = []
        main_size = sum(entry.quantity for entry in deck.main_deck)
        sideboard_size = sum(entry.quantity for entry in deck.sideboard)
        leader_count = sum(entry.quantity for entry in deck.leaders)
        base_count = sum(entry.quantity for entry in deck.bases)

        if deck.format_name == PREMIER:
            if leader_count != PREMIER_LEADER_COUNT:
                errors.append(f"Premier requires exactly 1 leader, found {leader_count}.")
            if base_count != 1:
                errors.append(f"Premier requires exactly 1 base, found {base_count}.")
            if main_size < PREMIER_MAIN_DECK_MIN:
                errors.append(f"Premier requires at least {PREMIER_MAIN_DECK_MIN} main-deck cards, found {main_size}.")
            if sideboard_size > PREMIER_SIDEBOARD_MAX:
                errors.append(f"Premier sideboard max is {PREMIER_SIDEBOARD_MAX}, found {sideboard_size}.")
        else:
            if leader_count != TWIN_SUNS_LEADER_COUNT:
                errors.append(f"Twin Suns requires exactly 2 leaders, found {leader_count}.")
            if base_count != 1:
                errors.append(f"Twin Suns requires exactly 1 base, found {base_count}.")
            if main_size < TWIN_SUNS_MAIN_DECK_MIN:
                errors.append(f"Twin Suns requires at least {TWIN_SUNS_MAIN_DECK_MIN} main-deck cards, found {main_size}.")
            if sideboard_size:
                errors.append("Twin Suns should not include a sideboard.")

        if leader_count and any(entry.quantity != 1 for entry in deck.leaders):
            errors.append("Leaders must appear as single copies.")
        if base_count and any(entry.quantity != 1 for entry in deck.bases):
            errors.append("Bases must appear as single copies.")

        main_counts = entry_quantity_by_name(deck.main_deck)
        sideboard_counts = entry_quantity_by_name(deck.sideboard)
        combined_counts = entry_quantity_by_name(deck.main_deck + deck.sideboard)
        copy_limit = 1 if deck.format_name == TWIN_SUNS else PREMIER_COPY_LIMIT
        # Per-card overrides come from card text like "A deck can have up to N copies of this card."
        card_by_name: dict[str, dict] = {}
        for entry in deck.main_deck + deck.sideboard:
            if entry.card and entry.display_name not in card_by_name:
                card_by_name[entry.display_name] = entry.card
        for name, quantity in sorted(combined_counts.items()):
            override = card_copy_override(card_by_name.get(name))
            effective_limit = max(copy_limit, override) if override is not None else copy_limit
            if quantity > effective_limit:
                errors.append(f"{name} appears {quantity} times; the format limit is {effective_limit}.")

        if deck.format_name == TWIN_SUNS:
            alignment = shared_alignment(deck.leaders)
            if not alignment:
                errors.append("Twin Suns leaders must share Heroism or Villainy.")

        illegal_card_types = [entry.display_name for entry in deck.main_deck if entry.card and entry.card["card_type"] in {"Leader", "Base"}]
        if illegal_card_types:
            errors.append(f"Main deck contains non-draw-deck cards: {', '.join(illegal_card_types[:5])}.")

        aspect_penalties = calculate_aspect_penalties(deck)
        if aspect_penalties["cards"]:
            warnings.append(
                f"{aspect_penalties['card_count']} cards are off-aspect and will cost extra resources unless you plan to pay the penalty."
            )

        return {
            "format": deck.format_name,
            "legal": not errors,
            "errors": errors,
            "warnings": warnings,
            "counts": {
                "leaders": leader_count,
                "bases": base_count,
                "main_deck": main_size,
                "sideboard": sideboard_size,
            },
            "copy_counts": {
                "main_deck": dict(sorted(main_counts.items())),
                "sideboard": dict(sorted(sideboard_counts.items())),
            },
            "aspect_penalties": aspect_penalties,
        }

    def _resolve_deck_input(
        self,
        *,
        session_id: str | None,
        decklist: str | dict[str, Any] | None,
        format_name: str,
    ) -> ParsedDeck:
        if session_id:
            return self._get_session(session_id).deck
        if decklist is not None:
            return self.resolve_deck(self.parse_decklist(decklist=decklist, format_name=format_name))
        raise ValueError("Provide either a session_id or a decklist.")

    def _resolve_entry(self, entry: DeckCardEntry, *, cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
        if entry.lookup_id and entry.lookup_id in cache:
            return cache[entry.lookup_id]

        if self.card_service.catalog.is_available():
            preferred_type = "Leader" if entry.zone == "leaders" else "Base" if entry.zone == "bases" else None
            exclude_types = {"Leader", "Base"} if entry.zone in {"main_deck", "sideboard"} else None
            if entry.set_code and entry.card_number:
                local_card = self.card_service.catalog.lookup(entry.set_code, entry.card_number)
                if local_card:
                    card = local_card.to_dict()
                    cache[str(card["lookup_id"])] = card
                    return card
            local_card = self.card_service.catalog.lookup_by_name(
                entry.name,
                preferred_type=preferred_type,
                exclude_types=exclude_types,
            )
            if local_card:
                card = local_card.to_dict()
                cache[str(card["lookup_id"])] = card
                return card

        if entry.set_code and entry.card_number:
            card = self.card_service.lookup_card(set_code=entry.set_code, card_number=entry.card_number)
        else:
            card = self.card_service.lookup_card(name=entry.name)

        cache[str(card["lookup_id"])] = card
        return card

    def _build_session(self, *, session_id: str, deck: ParsedDeck, shuffle: bool) -> DeckSession:
        card_index = {str(entry.card["lookup_id"]): entry.card for entry in deck.leaders + deck.bases + deck.main_deck + deck.sideboard if entry.card}
        library = [str(entry.card["lookup_id"]) for entry in deck.main_deck for _ in range(entry.quantity) if entry.card]
        if shuffle:
            random.shuffle(library)
        leaders = [
            GameCardState(
                instance_id=f"leader-{index + 1}",
                lookup_id=str(entry.card["lookup_id"]),
                name=entry.display_name,
                zone="leader",
                ready=True,
                arena=first_arena(entry.card),
                deployed=False,
            )
            for index, entry in enumerate(deck.leaders)
            if entry.card
        ]
        bases = [
            GameCardState(
                instance_id=f"base-{index + 1}",
                lookup_id=str(entry.card["lookup_id"]),
                name=entry.display_name,
                zone="base",
                ready=True,
                arena="base",
                deployed=True,
            )
            for index, entry in enumerate(deck.bases)
            if entry.card
        ]
        return DeckSession(
            session_id=session_id,
            deck=deck,
            card_index=card_index,
            library=library,
            leaders=leaders,
            bases=bases,
        )

    def _get_session(self, session_id: str) -> DeckSession:
        session = self.sessions.get(session_id)
        if not session:
            raise ValueError(f"No deck session found for '{session_id}'. Upload a deck first.")
        return session

    def _draw_cards(self, session: DeckSession, count: int) -> list[dict[str, Any]]:
        drawn: list[dict[str, Any]] = []
        for _ in range(max(0, count)):
            if not session.library:
                break
            lookup_id = session.library.pop(0)
            session.hand.append(lookup_id)
            drawn.append(session.card_index[lookup_id])
        return drawn

    def _move_existing_state(
        self,
        *,
        session: DeckSession,
        card_name: str,
        source_zone: str,
        destination: str,
        ready: bool | None = None,
        damage: int | None = None,
        experience: int | None = None,
        shield: int | None = None,
    ) -> GameCardState:
        if source_zone == "discard":
            discard_index = find_card_index(session.discard, session.card_index, card_name)
            lookup_id = session.discard.pop(discard_index)
            raw_card = session.card_index[lookup_id]
            card_state = GameCardState(
                instance_id=session.next_instance_id("board"),
                lookup_id=lookup_id,
                name=str(raw_card["display_name"]),
                zone=destination,
                ready=True if ready is None else ready,
                damage=max(0, damage or 0),
                experience=max(0, experience or 0),
                shield=max(0, shield or 0),
                arena=destination if destination in {"ground", "space"} else None,
                deployed=True,
            )
        else:
            card_state = self._find_game_card(session, card_name=card_name, zone=source_zone)
            self._remove_state_from_zone(session, card_state, source_zone)
            if destination == "discard":
                session.discard.append(card_state.lookup_id)
                card_state.zone = "discard"
                card_state.ready = False
                card_state.arena = None
                card_state.deployed = False
                return card_state

        if ready is not None:
            card_state.ready = ready
        if damage is not None:
            card_state.damage = max(0, damage)
        if experience is not None:
            card_state.experience = max(0, experience)
        if shield is not None:
            card_state.shield = max(0, shield)

        card_state.zone = destination
        if destination in {"ground", "space"}:
            card_state.arena = destination
            card_state.deployed = True
        elif destination == "resource":
            card_state.arena = None
            card_state.deployed = True
        elif destination == "leader":
            card_state.deployed = False
        elif destination == "upgrade":
            card_state.deployed = True
        self._append_state_to_zone(session, card_state, destination)
        return card_state

    def _append_state_to_zone(self, session: DeckSession, card_state: GameCardState, zone: str) -> None:
        if zone == "ground":
            session.ground_arena.append(card_state)
            return
        if zone == "space":
            session.space_arena.append(card_state)
            return
        if zone == "resource":
            session.resources.append(card_state)
            return
        if zone == "upgrade":
            session.upgrades.append(card_state)
            return
        if zone == "leader":
            session.leaders.append(card_state)
            return
        if zone == "base":
            session.bases.append(card_state)
            return
        raise ValueError(f"Unsupported destination zone: {zone}")

    def _remove_state_from_zone(self, session: DeckSession, card_state: GameCardState, zone: str) -> None:
        if zone == "ground":
            session.ground_arena.remove(card_state)
            return
        if zone == "space":
            session.space_arena.remove(card_state)
            return
        if zone == "resource":
            session.resources.remove(card_state)
            return
        if zone == "upgrade":
            session.upgrades.remove(card_state)
            return
        if zone == "leader":
            session.leaders.remove(card_state)
            return
        if zone == "base":
            session.bases.remove(card_state)
            return
        raise ValueError(f"Unsupported source zone: {zone}")

    def _find_game_card(self, session: DeckSession, *, card_name: str, zone: str) -> GameCardState:
        if zone == "ground":
            cards = session.ground_arena
        elif zone == "space":
            cards = session.space_arena
        elif zone == "resource":
            cards = session.resources
        elif zone == "upgrade":
            cards = session.upgrades
        elif zone == "leader":
            cards = session.leaders
        elif zone == "base":
            cards = session.bases
        else:
            raise ValueError(f"Unsupported zone: {zone}")

        lowered = card_name.strip().lower()
        for card in cards:
            if card.instance_id == card_name or card.name.lower() == lowered:
                return card
        raise ValueError(f"Card not found in {zone}: {card_name}")

    def _swap_cards(
        self,
        source_entries: list[DeckCardEntry],
        destination_entries: list[DeckCardEntry],
        name: str,
        count: int,
    ) -> None:
        source_index = find_entry_by_name(source_entries, name)
        source_entry = source_entries[source_index]
        if source_entry.quantity < count:
            raise ValueError(f"Cannot move {count} copies of {name}; only {source_entry.quantity} available.")

        source_entry.quantity -= count
        if source_entry.quantity == 0:
            source_entries.pop(source_index)

        destination_index = find_entry_by_name(destination_entries, name, raise_if_missing=False)
        if destination_index is None:
            destination_entries.append(
                DeckCardEntry(
                    quantity=count,
                    name=source_entry.name,
                    zone="sideboard" if source_entry.zone == "main_deck" else "main_deck",
                    set_code=source_entry.set_code,
                    card_number=source_entry.card_number,
                    card=source_entry.card,
                )
            )
        else:
            destination_entries[destination_index].quantity += count

    def _candidate_cards(
        self,
        *,
        goal_query: str,
        available_aspects: set[str],
        only_owned: bool = False,
    ) -> list[dict[str, Any]]:
        restrict_to_owned = only_owned and self.collection_service is not None
        if self.card_service.catalog.is_available():
            local_cards = [card.to_summary() for card in self.card_service.catalog.all_cards()]
            goal_tokens = tokenize_text(goal_query)
            ranked: list[tuple[tuple[int, int, int], dict[str, Any]]] = []
            for card in local_cards:
                if card["card_type"] in {"Leader", "Base"}:
                    continue
                if restrict_to_owned and not self._candidate_is_owned(card):
                    continue
                searchable = " ".join(
                    [
                        str(card.get("display_name", "")),
                        str(card.get("front_text", "")),
                        " ".join(card.get("traits", [])),
                        " ".join(card.get("keywords", [])),
                    ]
                ).lower()
                token_hits = sum(1 for token in goal_tokens if token in searchable)
                on_aspect = int(not (set(card.get("aspects", [])) - available_aspects))
                type_bonus = 1 if card["card_type"] == "Unit" else 0
                if goal_tokens and token_hits == 0 and on_aspect == 0 and not restrict_to_owned:
                    continue
                ranked.append(((on_aspect, token_hits, type_bonus), card))

            ranked.sort(key=lambda item: item[0], reverse=True)
            if ranked:
                return [card for _, card in ranked[:500]]

        pools: list[dict[str, Any]] = []
        seen: set[str] = set()
        queries = [goal_query] if goal_query and goal_query != "*" else ["unit event"]
        aspect_queries = sorted(available_aspects)
        for aspect in aspect_queries[:2]:
            queries.append(goal_query)
            try:
                result = self.card_service.search_cards(query=goal_query or "*", filters={"aspect": aspect}, limit=40)
            except Exception:
                continue
            for card in result["cards"]:
                if card["lookup_id"] not in seen:
                    pools.append(card)
                    seen.add(card["lookup_id"])

        for query in queries[:2]:
            try:
                result = self.card_service.search_cards(query=query or "*", limit=40)
            except Exception:
                continue
            for card in result["cards"]:
                if card["lookup_id"] not in seen:
                    pools.append(card)
                    seen.add(card["lookup_id"])
        if not pools:
            fallback = self.card_service.search_cards(query="unit event", limit=60)
            for card in fallback["cards"]:
                if card["lookup_id"] not in seen:
                    pools.append(card)
                    seen.add(card["lookup_id"])
        return pools

    def _pick_leaders(
        self,
        *,
        theme: str,
        format_name: str,
        leader_names: list[str] | None,
        only_owned: bool = False,
    ) -> list[dict[str, Any]]:
        if leader_names:
            leaders = []
            for name in leader_names:
                leader = self._resolve_leader_by_name(name)
                if leader:
                    leaders.append(leader)
        else:
            result = self.card_service.search_cards(query=theme, filters={"type": "Leader"}, limit=25)
            leaders = []
            for card in result["cards"][:15]:
                looked_up = self._safe_lookup(card)
                if looked_up is not None and looked_up.get("card_type") == "Leader":
                    leaders.append(looked_up)
        if not leaders:
            fallback = self.card_service.search_cards(query="*", filters={"type": "Leader"}, limit=25)
            leaders = []
            for card in fallback["cards"]:
                looked_up = self._safe_lookup(card)
                if looked_up is not None and looked_up.get("card_type") == "Leader":
                    leaders.append(looked_up)

        if only_owned and self.collection_service is not None:
            owned_leaders = [leader for leader in leaders if self._candidate_is_owned(leader)]
            if owned_leaders:
                leaders = owned_leaders

        if format_name == PREMIER:
            return leaders[:1]

        for first in leaders:
            for second in leaders:
                if first["lookup_id"] == second["lookup_id"]:
                    continue
                candidate_pair = [
                    DeckCardEntry(quantity=1, name=str(first["display_name"]), zone="leaders", card=first),
                    DeckCardEntry(quantity=1, name=str(second["display_name"]), zone="leaders", card=second),
                ]
                if shared_alignment(candidate_pair):
                    return [first, second]
        return leaders[:2]

    def _resolve_leader_by_name(self, name: str) -> dict[str, Any] | None:
        self.card_service._ensure_local_catalog()
        if self.card_service.catalog.is_available():
            card = self.card_service.catalog.lookup_by_name(name, preferred_type="Leader")
            if card:
                return card.to_dict()
        try:
            result = self.card_service.search_cards(name, filters={"type": "Leader"}, limit=5)
            lowered = name.strip().lower()
            for candidate in result["cards"]:
                if lowered in candidate["name"].lower():
                    return self.card_service.lookup_card(
                        set_code=candidate["set_code"], card_number=candidate["number"]
                    )
        except Exception:
            pass
        return None

    def _pick_base(
        self,
        *,
        base_name: str | None,
        aspect_pool: set[str],
        only_owned: bool = False,
    ) -> dict[str, Any]:
        if base_name:
            return self.card_service.lookup_card(name=base_name)

        query = " ".join(sorted(aspect_pool))
        result = self.card_service.search_cards(query=query or "*", filters={"type": "Base"}, limit=25)
        if not result["cards"]:
            result = self.card_service.search_cards(query="*", filters={"type": "Base"}, limit=25)

        if only_owned and self.collection_service is not None:
            for candidate in result["cards"]:
                if self.collection_service.is_owned(str(candidate["set_code"]), str(candidate["number"])):
                    looked_up = self._safe_lookup(candidate)
                    if looked_up is not None:
                        return looked_up

        for candidate in result["cards"]:
            looked_up = self._safe_lookup(candidate)
            if looked_up is not None:
                return looked_up

        return self.card_service.lookup_card(
            set_code=result["cards"][0]["set_code"], card_number=result["cards"][0]["number"]
        )

    def _parse_deck_dict(self, payload: dict[str, Any], format_name: str) -> ParsedDeck:
        parsed = ParsedDeck(format_name=format_name, title=payload.get("title"))
        parsed.leaders = parse_deck_section(payload.get("leaders", payload.get("leader", [])), zone="leaders")
        parsed.bases = parse_deck_section(payload.get("bases", payload.get("base", [])), zone="bases")
        parsed.main_deck = parse_deck_section(
            payload.get("main_deck", payload.get("deck", payload.get("main", []))),
            zone="main_deck",
        )
        parsed.sideboard = parse_deck_section(payload.get("sideboard", []), zone="sideboard")
        return parsed


def normalize_format(format_name: str) -> str:
    normalized = format_name.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported format '{format_name}'. Supported formats: {', '.join(sorted(SUPPORTED_FORMATS))}.")
    return normalized


def parse_deck_section(items: Any, *, zone: str) -> list[DeckCardEntry]:
    if isinstance(items, str):
        return [parse_deck_line(items, zone=zone)]
    entries: list[DeckCardEntry] = []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, str):
                entries.append(parse_deck_line(item, zone=zone))
            elif isinstance(item, dict):
                entries.append(
                    DeckCardEntry(
                        quantity=int(item.get("quantity", item.get("count", 1))),
                        name=str(item.get("name", "")).strip(),
                        zone=zone,
                        set_code=item.get("set_code") or item.get("set"),
                        card_number=item.get("card_number") or item.get("number"),
                    )
                )
    return entries


def parse_deck_line(line: str, *, zone: str) -> DeckCardEntry:
    cleaned = line.strip().lstrip("-*").strip()
    count = 1
    remainder = cleaned

    count_match = re.match(r"^(?P<count>\d+)x?\s+(?P<rest>.+)$", cleaned)
    if count_match:
        count = int(count_match.group("count"))
        remainder = count_match.group("rest").strip()

    bracketed_id = re.match(r"^\[(?P<set>[A-Z]{2,4})/(?P<number>[0-9]{1,3}[A-Z]?)\]\s*(?P<name>.+)$", remainder)
    if bracketed_id:
        return DeckCardEntry(
            quantity=count,
            name=bracketed_id.group("name").strip(),
            zone=zone,
            set_code=bracketed_id.group("set"),
            card_number=bracketed_id.group("number"),
        )

    # Bare `SET/NNN` (HoloScan-style export, no name attached). Name field is
    # left empty — the resolver will populate it from the catalog using
    # set_code + card_number, which is the canonical lookup path. Numbers can
    # run to 4 digits (foil/hyperspace variants reach 4-digit numbering).
    bare_id = re.match(r"^(?P<set>[A-Z]{2,4})/(?P<number>[0-9]{1,4}[A-Z]?)\s*$", remainder)
    if bare_id:
        return DeckCardEntry(
            quantity=count,
            name="",
            zone=zone,
            set_code=bare_id.group("set"),
            card_number=bare_id.group("number"),
        )

    prefixed_id = re.match(r"^(?P<set>[A-Z]{2,4})[ /](?P<number>[0-9]{1,3}[A-Z]?)\s+(?P<name>.+)$", remainder)
    if prefixed_id:
        return DeckCardEntry(
            quantity=count,
            name=prefixed_id.group("name").strip(),
            zone=zone,
            set_code=prefixed_id.group("set"),
            card_number=prefixed_id.group("number"),
        )

    trailing_set = re.match(r"^(?P<name>.+?)\s+\((?P<set>[A-Z]{2,4})\)\s*$", remainder)
    if trailing_set:
        return DeckCardEntry(
            quantity=count,
            name=trailing_set.group("name").strip(),
            zone=zone,
            set_code=trailing_set.group("set"),
        )

    return DeckCardEntry(quantity=count, name=remainder, zone=zone)


def collapse_entries(parsed: ParsedDeck) -> ParsedDeck:
    return ParsedDeck(
        format_name=parsed.format_name,
        title=parsed.title,
        leaders=merge_entries(parsed.leaders),
        bases=merge_entries(parsed.bases),
        main_deck=merge_entries(parsed.main_deck),
        sideboard=merge_entries(parsed.sideboard),
    )


def merge_entries(entries: list[DeckCardEntry]) -> list[DeckCardEntry]:
    merged: dict[str, DeckCardEntry] = {}
    order: list[str] = []
    for entry in entries:
        key = entry.lookup_id or entry.name.lower()
        if key not in merged:
            merged[key] = DeckCardEntry(
                quantity=entry.quantity,
                name=entry.name,
                zone=entry.zone,
                set_code=entry.set_code,
                card_number=entry.card_number,
                card=entry.card,
            )
            order.append(key)
        else:
            merged[key].quantity += entry.quantity
    return [merged[key] for key in order]


def calculate_aspect_penalties(deck: ParsedDeck) -> dict[str, Any]:
    available_aspects = collect_deck_aspects(deck)
    penalties: list[dict[str, Any]] = []
    total_penalty = 0

    for entry in deck.main_deck:
        if not entry.card:
            continue
        missing_aspects = sorted(set(entry.card.get("aspects", [])) - available_aspects)
        if not missing_aspects:
            continue
        penalty = len(missing_aspects) * ASPECT_PENALTY_PER_MISSING_ICON
        total_penalty += penalty * entry.quantity
        penalties.append(
            {
                "card": entry.display_name,
                "quantity": entry.quantity,
                "missing_aspects": missing_aspects,
                "extra_cost_per_copy": penalty,
            }
        )

    return {
        "available_aspects": sorted(available_aspects),
        "card_count": sum(item["quantity"] for item in penalties),
        "total_extra_resource_burden": total_penalty,
        "cards": penalties,
    }


def collect_deck_aspects(deck: ParsedDeck) -> set[str]:
    aspects: set[str] = set()
    for entry in deck.leaders + deck.bases:
        if entry.card:
            aspects.update(entry.card.get("aspects", []))
    return aspects


def shared_alignment(leaders: list[DeckCardEntry]) -> str | None:
    if len(leaders) < 2:
        return None
    leader_aspects = [set(entry.card.get("aspects", [])) if entry.card else set() for entry in leaders]
    if all("Heroism" in aspects for aspects in leader_aspects):
        return "Heroism"
    if all("Villainy" in aspects for aspects in leader_aspects):
        return "Villainy"
    return None


def summarize_deck(deck: ParsedDeck) -> dict[str, Any]:
    return {
        "format": deck.format_name,
        "leaders": [entry.display_name for entry in deck.leaders],
        "bases": [entry.display_name for entry in deck.bases],
        "main_deck_size": sum(entry.quantity for entry in deck.main_deck),
        "sideboard_size": sum(entry.quantity for entry in deck.sideboard),
        "main_deck": [entry_to_export(entry) for entry in deck.main_deck],
        "sideboard": [entry_to_export(entry) for entry in deck.sideboard],
    }


def entry_to_export(entry: DeckCardEntry) -> dict[str, Any]:
    return {
        "quantity": entry.quantity,
        "name": entry.display_name,
        "lookup_id": entry.lookup_id,
        "set_code": entry.set_code,
        "card_number": entry.card_number,
    }


def summarize_for_zone(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "lookup_id": card["lookup_id"],
        "name": card["display_name"],
        "type": card["card_type"],
        "cost": card.get("cost"),
        "power": card.get("power"),
        "hp": card.get("hp"),
        "aspects": card.get("aspects", []),
    }


def summarize_game_card(card_state: GameCardState, card_index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    raw_card = card_index[card_state.lookup_id]
    return {
        **summarize_for_zone(raw_card),
        "instance_id": card_state.instance_id,
        "zone": card_state.zone,
        "arena": card_state.arena,
        "ready": card_state.ready,
        "damage": card_state.damage,
        "experience": card_state.experience,
        "shield": card_state.shield,
        "power_bonus": card_state.power_bonus,
        "hp_bonus": card_state.hp_bonus,
        "granted_keywords": card_state.granted_keywords,
        "deployed": card_state.deployed,
        "attached_to_instance_id": card_state.attached_to_instance_id,
        "attached_to_name": card_state.attached_to_name,
    }


def expand_entries(entries: list[DeckCardEntry]) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for entry in entries:
        if not entry.card:
            continue
        expanded.extend([entry.card] * entry.quantity)
    return expanded


def entry_quantity_by_name(entries: list[DeckCardEntry]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for entry in entries:
        counter[entry.display_name] += entry.quantity
    return counter


def parse_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def bucket_cost(cost: int | None) -> str:
    if cost is None:
        return "X"
    if cost >= 7:
        return "7+"
    return str(cost)


def detect_roles(card: dict[str, Any]) -> list[str]:
    text = " ".join([str(card.get("front_text", "")), str(card.get("epic_action", "")), str(card.get("back_text", ""))]).lower()
    roles: list[str] = []
    for role, patterns in ROLE_PATTERNS.items():
        if any(pattern in text for pattern in patterns):
            roles.append(role)
    if card.get("card_type") == "Unit":
        roles.append("board_presence")
    return roles


def build_style_notes(
    *,
    type_counts: Counter[str],
    role_counts: Counter[str],
    curve: Counter[str],
) -> list[str]:
    notes: list[str] = []
    if type_counts.get("Unit", 0) >= 20:
        notes.append("Board-centric shell with enough units to pressure both arenas.")
    if role_counts.get("removal", 0) >= 6:
        notes.append("Removal density looks healthy enough for interactive matchups.")
    if int(curve.get("1", 0)) + int(curve.get("2", 0)) < 8:
        notes.append("Early curve is light; consider adding more one- and two-cost plays.")
    if role_counts.get("card_advantage", 0) >= 5:
        notes.append("The list has a solid value engine for grindy games.")
    if not notes:
        notes.append("Profile looks balanced, but the deck would benefit from matchup-specific tuning.")
    return notes


def normalize_meta_context(
    *,
    target_matchups: list[str] | None,
    meta_context: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized_matchups = [normalize_matchup(matchup) for matchup in (target_matchups or []) if matchup]
    pressure: dict[str, float] = {}
    priorities: list[str] = []
    notes: list[str] = []

    if meta_context:
        raw_matchups = meta_context.get("target_matchups") or meta_context.get("matchups") or []
        normalized_matchups.extend(normalize_matchup(matchup) for matchup in raw_matchups if matchup)
        raw_pressure = meta_context.get("pressure") or {}
        for matchup_name, weight in raw_pressure.items():
            normalized_name = normalize_matchup(str(matchup_name))
            if normalized_name in MATCHUP_PROFILES:
                pressure[normalized_name] = float(weight)
        priorities = [str(item) for item in meta_context.get("priorities", []) if item]
        notes = [str(item) for item in meta_context.get("notes", []) if item]

    deduped_matchups = list(dict.fromkeys(matchup for matchup in normalized_matchups if matchup in MATCHUP_PROFILES))
    if not pressure and deduped_matchups:
        equal_weight = round(1 / len(deduped_matchups), 3)
        pressure = {matchup: equal_weight for matchup in deduped_matchups}

    return {
        "target_matchups": deduped_matchups,
        "pressure": pressure,
        "priorities": priorities,
        "notes": notes,
    }


def evaluate_matchups(
    *,
    main_cards: list[dict[str, Any]],
    role_counts: Counter[str],
    keyword_counts: Counter[str],
    early_curve: int,
    meta_summary: dict[str, Any],
) -> dict[str, Any]:
    matchup_scores: dict[str, Any] = {}
    arena_counts = Counter(arena for card in main_cards for arena in card.get("arenas", []))
    for matchup in meta_summary["target_matchups"]:
        profile = MATCHUP_PROFILES.get(matchup, {})
        score = 40.0
        notes: list[str] = []
        for role_name, weight in profile.get("roles", {}).items():
            role_value = role_counts.get(role_name, 0)
            score += min(weight, role_value)
            if role_value:
                notes.append(f"{role_name.replace('_', ' ')} support: {role_value}.")
        for keyword_name, weight in profile.get("keywords", {}).items():
            keyword_value = keyword_counts.get(keyword_name, 0)
            score += min(weight, keyword_value)
            if keyword_value:
                notes.append(f"{keyword_name} count: {keyword_value}.")
        for arena_name, weight in profile.get("arena", {}).items():
            arena_value = arena_counts.get(arena_name, 0)
            score += min(weight, arena_value / 2)
            if arena_value:
                notes.append(f"{arena_name.lower()} presence: {arena_value}.")
        score += min(profile.get("early_curve", 0), early_curve / 2)
        matchup_scores[matchup] = {
            "score": round(max(0.0, min(100.0, score)), 2),
            "notes": notes[:3],
        }
    return matchup_scores


def compile_goal_query(goal: str) -> str:
    lowered = goal.strip().lower()
    if not lowered:
        return "*"
    pieces = [goal]
    for key, value in GOAL_QUERY_HINTS.items():
        if key in lowered:
            pieces.append(value)
    return " ".join(dict.fromkeys(pieces))


def tokenize_text(text: str) -> list[str]:
    return [
        token
        for token in re.split(r"[^a-z0-9]+", text.lower())
        if len(token) >= 3 and token not in STOPWORDS
    ]


def score_candidate_for_matchups(candidate: dict[str, Any], meta_summary: dict[str, Any]) -> tuple[float, list[str]]:
    total_score = 0.0
    reasons: list[str] = []
    roles = set(detect_roles(candidate))
    keywords = set(candidate.get("keywords", []))
    arenas = set(candidate.get("arenas", []))
    for matchup in meta_summary["target_matchups"]:
        profile = MATCHUP_PROFILES.get(matchup)
        if not profile:
            continue
        matchup_weight = meta_summary["pressure"].get(matchup, 1.0)
        matchup_score = 0.0
        matchup_reasons: list[str] = []
        for role_name, weight in profile.get("roles", {}).items():
            if role_name in roles:
                matchup_score += weight * matchup_weight
                matchup_reasons.append(role_name.replace("_", " "))
        for keyword_name, weight in profile.get("keywords", {}).items():
            if keyword_name in keywords:
                matchup_score += weight * matchup_weight
                matchup_reasons.append(keyword_name)
        for arena_name, weight in profile.get("arena", {}).items():
            if arena_name in arenas:
                matchup_score += weight * matchup_weight
                matchup_reasons.append(f"{arena_name.lower()} presence")
        if matchup_score:
            reasons.append(f"Useful into {matchup}: {', '.join(dict.fromkeys(matchup_reasons))}.")
        total_score += matchup_score
    return total_score, reasons


def quantity_for_cost(entries: list[DeckCardEntry], minimum: int, maximum: int) -> int:
    quantity = 0
    for entry in entries:
        if not entry.card:
            continue
        cost = parse_int(entry.card.get("cost"))
        if cost is not None and minimum <= cost <= maximum:
            quantity += entry.quantity
    return quantity


def power_score(card: dict[str, Any]) -> float:
    """Intrinsic card power, no deck context.

    Calibrated against 10 PQ Premier decks (median 8.2/card). Stat efficiency
    × 3 capped at 12 for units; +2.5 per keyword; rarity bump per design tier;
    utility verbs for events/upgrades; -4 for blank-text vanillas.
    """
    score = 0.0
    cost = parse_int(card.get("cost")) or 1
    ctype = card.get("card_type") or card.get("Type") or ""
    if ctype == "Unit":
        p = parse_int(card.get("power")) or 0
        h = parse_int(card.get("hp")) or 0
        eff = (p + h) / max(cost, 1)
        score += min(eff * 3.0, 12.0)
    keywords = card.get("keywords") or card.get("Keywords") or []
    score += len(keywords) * 2.5
    rarity = str(card.get("rarity") or card.get("Rarity") or "").capitalize()
    score += RARITY_BUMP.get(rarity, 0.0)
    text_lower = (
        (card.get("front_text") or card.get("FrontText") or "").lower()
        + " "
        + (card.get("epic_action") or card.get("EpicAction") or "").lower()
    )
    if ctype in ("Event", "Upgrade"):
        if any(v in text_lower for v in ("defeat", "destroy", "exhaust", "deal", "damage")):
            score += 2.0
        if "draw" in text_lower:
            score += 3.0
        if "heal" in text_lower:
            score += 2.0
    if not text_lower.strip():
        score += BLANK_TEXT_PENALTY
    return score


def generation_score(
    *,
    card: dict[str, Any],
    theme: str,
    aspect_pool: set[str],
    budget: str | None,
    meta_summary: dict[str, Any] | None = None,
    format_name: str = PREMIER,
) -> float:
    score = 0.0
    searchable = " ".join(
        [
            str(card.get("display_name", "")),
            str(card.get("front_text", "")),
            " ".join(card.get("traits", [])),
            " ".join(card.get("keywords", [])),
        ]
    ).lower()
    for token in tokenize_text(theme):
        if token in searchable:
            score += 6

    missing_aspects = set(card.get("aspects", [])) - aspect_pool
    off_aspect_w = (
        OFF_ASPECT_PER_ICON_TWIN_SUNS
        if format_name == TWIN_SUNS
        else OFF_ASPECT_PER_ICON_PREMIER
    )
    score += len(missing_aspects) * off_aspect_w

    cost = parse_int(card.get("cost"))
    if cost is not None:
        if cost <= 2:
            score += 5
        elif cost <= 4:
            score += 4
        else:
            score += 1
        # Twin Suns: extra weight on cheap units to honor the lower-curve advice.
        if format_name == TWIN_SUNS and cost <= 2:
            score += 2

    if format_name == TWIN_SUNS:
        keywords = set(card.get("keywords", []) or [])
        if keywords & TWIN_SUNS_BASE_PRESSURE_KEYWORDS:
            score += TWIN_SUNS_BASE_PRESSURE_BONUS
        # Leader-interaction synergy: cards that mention "leader" in text are
        # disproportionately good in a 2-leader format.
        front_text = str(card.get("front_text", "") or "").lower()
        if "leader" in front_text:
            score += TWIN_SUNS_LEADER_SYNERGY_BONUS

    # Aspect affinity: when a card both shares an aspect with the deck AND
    # expresses that aspect's signature role (per community guides), reward
    # consistency. Capped at one bonus per card so dual-aspect cards don't
    # double-stack.
    card_aspects = set(card.get("aspects", []))
    shared_aspects = card_aspects & aspect_pool
    kw_set = set(card.get("keywords", []) or [])
    if shared_aspects:
        text_lower = str(card.get("front_text", "") or "").lower()
        for asp in shared_aspects:
            sig = ASPECT_AFFINITY.get(asp)
            if not sig:
                continue
            if (kw_set & sig["keywords"]) or any(
                tok in text_lower for tok in sig["text_tokens"]
            ):
                score += ASPECT_AFFINITY_BONUS
                break

        # Color-pie: keyword printed in its primary aspect's home is more
        # internally-consistent. Capped at one bonus per card.
        for asp in shared_aspects:
            primary = PRIMARY_KEYWORD_BY_ASPECT.get(asp, set())
            if kw_set & primary:
                score += COLOR_PIE_BONUS
                break

    # Keyword synergy pairs: stack a bonus per designed-combo pair the card
    # carries. Aspect-independent — these are mechanical interactions.
    if len(kw_set) >= 2:
        for pair in KEYWORD_SYNERGY_PAIRS:
            if pair <= kw_set:
                score += KEYWORD_SYNERGY_BONUS

    rarity = str(card.get("rarity", "")).lower()
    if budget and budget.lower() in {"budget", "cheap"}:
        if rarity in {"common", "uncommon"}:
            score += 4
        elif rarity == "legendary":
            score -= 4

    if card.get("card_type") == "Unit":
        score += 4
    if meta_summary:
        matchup_score, _ = score_candidate_for_matchups(card, meta_summary)
        score += matchup_score

    score += POWER_WEIGHT * power_score(card)
    return score


def recommended_quantity(card: dict[str, Any]) -> int:
    cost = parse_int(card.get("cost"))
    rarity = str(card.get("rarity", "")).lower()
    if rarity == "legendary":
        return 2
    if cost is not None and cost >= 6:
        return 2
    return 3


def trim_to_size(entries: list[DeckCardEntry], target_size: int) -> list[DeckCardEntry]:
    trimmed: list[DeckCardEntry] = []
    running_total = 0
    for entry in entries:
        if running_total >= target_size:
            break
        remaining = target_size - running_total
        quantity = min(entry.quantity, remaining)
        trimmed.append(
            DeckCardEntry(
                quantity=quantity,
                name=entry.name,
                zone=entry.zone,
                set_code=entry.set_code,
                card_number=entry.card_number,
                card=entry.card,
            )
        )
        running_total += quantity
    return merge_entries(trimmed)


def normalize_lookup_number(card_number: str) -> str:
    cleaned = str(card_number).strip().upper()
    digits = "".join(character for character in cleaned if character.isdigit())
    suffix = cleaned[len(digits):] if cleaned.startswith(digits) else ""
    if digits:
        return f"{int(digits):03d}{suffix}"
    return cleaned


def normalize_zone(zone: str) -> str:
    normalized = zone.strip().lower().replace("_", " ").replace("-", " ")
    aliases = {
        "ground arena": "ground",
        "space arena": "space",
        "board": "ground",
        "resource": "resource",
        "resources": "resource",
        "leader zone": "leader",
        "leaders": "leader",
        "bases": "base",
    }
    return aliases.get(normalized, normalized)


def normalize_matchup(name: str) -> str:
    normalized = name.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "token": "tokens",
    }
    return aliases.get(normalized, normalized)


def first_arena(card: dict[str, Any] | None) -> str | None:
    if not card:
        return None
    arenas = card.get("arenas", [])
    if not arenas:
        return None
    return str(arenas[0]).lower()


def find_entry_by_name(entries: list[DeckCardEntry], name: str, *, raise_if_missing: bool = True) -> int | None:
    lowered = name.strip().lower()
    for index, entry in enumerate(entries):
        if entry.display_name.lower() == lowered or entry.name.lower() == lowered:
            return index
    if raise_if_missing:
        raise ValueError(f"Card not found in zone: {name}")
    return None


def find_card_by_name(cards: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    lowered = name.strip().lower()
    for card in cards:
        if str(card.get("display_name", "")).lower() == lowered:
            return card
    return None


def summarize_card_counts(entries: list[DeckCardEntry]) -> dict[str, int]:
    return dict(sorted(entry_quantity_by_name(entries).items()))


def _debug_entries(entries: list[DeckCardEntry]) -> list[tuple[int, str]]:
    return [(entry.quantity, entry.display_name) for entry in entries]


def _entries_with_cards(entries: list[DeckCardEntry]) -> list[DeckCardEntry]:
    return [entry for entry in entries if entry.card]


def _cards_for_entries(entries: list[DeckCardEntry]) -> list[dict[str, Any]]:
    return [entry.card for entry in entries if entry.card]


def find_card_index(zone: list[str], card_index: dict[str, dict[str, Any]], name: str) -> int:
    lowered = name.strip().lower()
    for index, lookup_id in enumerate(zone):
        card = card_index[lookup_id]
        if str(card["display_name"]).lower() == lowered or str(card["name"]).lower() == lowered:
            return index
    raise ValueError(f"Card not found: {name}")
