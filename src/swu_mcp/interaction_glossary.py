"""SWU interaction glossary — token vocabulary for the provides/needs scoring model.

Built from full SOR/SHD/TWI/JTL/LOF/IBH/SOP/LAW catalog (4812 unique printings).
Counts in comments are: (cards_that_have_token, cards_whose_text_pays_off_token).
Higher payoff count = stronger interaction signal.

Use:
    from swu_mcp.interaction_glossary import provides_set, needs_set
    p = provides_set(card)   # what this card brings to the table
    n = needs_set(card)      # what this card looks for in teammates
    score = len(needs(D) & provides(C)) + len(needs(C) & provides(D))
"""

import re
from typing import Iterable

# ---- Provides vocabulary (machine-readable from card data fields) ----

TRAITS_ALL = [
    "VEHICLE", "FORCE", "UNDERWORLD", "REBEL", "IMPERIAL", "FIGHTER",
    "REPUBLIC", "JEDI", "TRANSPORT", "TROOPER", "TACTIC", "FRINGE",
    "BOUNTY HUNTER", "CAPITAL SHIP", "SEPARATIST", "OFFICIAL", "DROID",
    "PILOT", "CREATURE", "RESISTANCE", "ITEM", "SITH", "MANDALORIAN",
    "SPECTRE", "FIRST ORDER", "WEAPON", "TRICK", "INNATE", "SUPPLY",
    "LEARNED", "GAMBIT", "NIGHT", "CLONE", "PLAN", "WOOKIEE",
    "LIGHTSABER", "SPEEDER", "CONDITION", "WALKER", "TWI'LEK",
]

KEYWORDS_ALL = [
    "Sentinel", "Ambush", "Overwhelm", "Raid", "Restore", "Shielded",
    "Saboteur", "Piloting", "Hidden", "Grit", "Smuggle", "Coordinate",
    "Exploit", "Bounty",
]

TYPES_ALL = ["Unit", "Event", "Leader", "Upgrade", "Base"]
ARENAS_ALL = ["Ground", "Space"]
ASPECTS_ALL = ["Heroism", "Villainy", "Cunning", "Command", "Vigilance", "Aggression"]


# ---- Needs vocabulary (parsed from card text — only tokens with real payoff signal) ----

# Traits with strong text-reference signal. Number = cards whose text references it
# without themselves having the trait (true payoff cards).
TRAITS_NEEDED = {
    "VEHICLE":        386,   # Rose Tico, Pilot effects, "give a Vehicle +X"
    "PILOT":          212,   # "Deploy a Pilot", piloting payoffs
    "DROID":          90,    # droid-tribal payoffs
    "FIGHTER":        72,    # ace-fighter / squadron themes
    "TROOPER":        55,    # trooper rally effects
    "UNDERWORLD":     52,    # underworld synergies
    "CLONE":          48,    # clone rally
    "BOUNTY HUNTER":  38,    # bounty payoff
    "JEDI":           32,    # jedi council theme
    "REBEL":          30,
    "SPECTRE":        29,
    "CREATURE":       25,
    "SEPARATIST":     23,
    "MANDALORIAN":    22,
    "TRANSPORT":      22,
    "LIGHTSABER":     21,    # lightsaber-upgrade payoffs
    "REPUBLIC":       19,
    "SITH":           19,
    "RESISTANCE":     18,
    "IMPERIAL":       15,
    "CAPITAL SHIP":   11,
    "FIRST ORDER":    11,
    "ITEM":           9,
    "WOOKIEE":        6,
    # Skip: low-signal traits (≤ 5 mentions) — too few cards to matter.
}

# Keywords worth scoring as needs (real payoff, not self-mention).
# (cards_with_keyword, cards_that_pay_it_off)
KEYWORDS_NEEDED = {
    "Sentinel":   124,   # "deal damage to a non-Sentinel unit", etc.
    "Bounty":     72,    # bounty hunter archetype payoff
    "Smuggle":    16,
    "Overwhelm":  14,
    "Raid":       12,
    "Shielded":   9,
    "Saboteur":   7,
    "Restore":    4,
    "Exploit":    4,
    # Skip: Piloting/Hidden/Grit/Coordinate/Ambush — 0–2 payoff cards each.
}

# Aspects mentioned in payoff text (e.g., "if you control a Heroism unit, ...").
# All six aspects show ~90–140 text mentions — real signal across the board.
ASPECTS_NEEDED = {a: 100 for a in ASPECTS_ALL}


# ---- Ambiguity blocklist ----

# "Force" the trait gets ~272 false-positive hits from the Force-token mechanic
# ("use the Force", "your Force token", "the Force is with you"). Filter those.
FORCE_TOKEN_MECHANIC = re.compile(
    r"(use the Force|your Force token|the Force is with you|create your Force token|lose your Force token)",
    re.IGNORECASE,
)

# Multi-word traits need word-boundary care.
def _trait_pattern(trait: str) -> re.Pattern[str]:
    # Plural-tolerant, word-boundary, case-insensitive.
    return re.compile(r"\b" + re.escape(trait) + r"s?\b", re.IGNORECASE)


# ---- Public API ----

def provides_set(card: dict) -> set[str]:
    """What this card supplies to the deck — for matching against needs."""
    out: set[str] = set()
    for t in (card.get("traits") or card.get("Traits") or []):
        out.add(f"trait:{t}")
    for k in (card.get("keywords") or card.get("Keywords") or []):
        out.add(f"kw:{k}")
    if (ct := card.get("card_type") or card.get("Type")):
        out.add(f"type:{ct}")
    for a in (card.get("aspects") or card.get("Aspects") or []):
        out.add(f"aspect:{a}")
    for ar in (card.get("arenas") or card.get("Arenas") or []):
        out.add(f"arena:{ar}")
    return out


def needs_set(card: dict, *, score_aspects: bool = True) -> set[str]:
    """What this card's text references as a payoff target.

    Reads FrontText + EpicAction + BackText so leader cards (which carry their
    deployable-unit ability on the back) are scored on both sides.

    Aspect-needs are emitted by default; interaction_score filters them down
    to the deck's actual aspect pool so multi-aspect cards don't get free
    matches against tokens the deck can't legitimately satisfy.
    """
    text_parts = [
        card.get("front_text") or card.get("FrontText") or "",
        card.get("epic_action") or card.get("EpicAction") or "",
        card.get("back_text") or card.get("BackText") or "",
    ]
    text = " ".join(text_parts)
    if not text:
        return set()

    out: set[str] = set()
    own_traits = set(card.get("traits") or card.get("Traits") or [])

    # Strip Force-token mechanic before scanning so FORCE trait isn't false-flagged
    sanitized = FORCE_TOKEN_MECHANIC.sub("", text)

    for trait in TRAITS_NEEDED:
        if trait in own_traits:
            continue  # self-mention, not interaction
        if _trait_pattern(trait).search(sanitized):
            out.add(f"trait:{trait}")

    own_keywords = set(card.get("keywords") or card.get("Keywords") or [])
    for kw in KEYWORDS_NEEDED:
        if kw in own_keywords:
            continue
        if re.search(r"\b" + re.escape(kw) + r"\b", text):
            out.add(f"kw:{kw}")

    if score_aspects:
        own_aspects = set(card.get("aspects") or card.get("Aspects") or [])
        for asp in ASPECTS_NEEDED:
            if asp in own_aspects:
                continue
            if re.search(r"\b" + re.escape(asp) + r"\b", text):
                out.add(f"aspect:{asp}")

    return out


def _deck_aspect_pool(deck_so_far: Iterable[dict]) -> set[str]:
    """Return the set of aspect tokens legitimately available in the deck."""
    pool: set[str] = set()
    for d in deck_so_far:
        for a in (d.get("aspects") or d.get("Aspects") or []):
            pool.add(f"aspect:{a}")
    return pool


def _filter_aspect_needs(needs: set[str], aspect_pool: set[str]) -> set[str]:
    """Drop aspect-needs that the deck's aspect pool can't legitimately satisfy."""
    non_aspect = {t for t in needs if not t.startswith("aspect:")}
    valid_aspects = {t for t in needs if t.startswith("aspect:")} & aspect_pool
    return non_aspect | valid_aspects


def interaction_score(
    candidate: dict,
    deck_so_far: Iterable[dict],
    *,
    w_payoff: float = 8.0,
    w_enabler: float = 8.0,
    w_trait_overlap: float = 0.5,
    cap_per_pair: int = 1,
    score_aspects: bool = True,
) -> float:
    """Score a candidate card against the cards already drafted into the deck.

    cap_per_pair: maximum payoff/enabler matches counted per (candidate, D) pair.
        Default 1 prevents broad-needs cards (those that match many tokens at once)
        from dominating. Set higher (e.g., 3) to reward deeper synergy.
    score_aspects: include aspect-token matches, filtered to the deck's actual
        aspect pool. A card mentioning Heroism only scores in a deck whose
        leader/base/main actually contain Heroism — so a Sabine-style card with
        all six aspects in her text only matches the 2 (or 3, or 4) the deck
        legitimately runs.
    """
    deck_list = list(deck_so_far)
    aspect_pool = _deck_aspect_pool(deck_list) if score_aspects else set()

    cand_provides = provides_set(candidate)
    cand_needs = needs_set(candidate, score_aspects=score_aspects)
    if score_aspects:
        cand_needs = _filter_aspect_needs(cand_needs, aspect_pool)
    cand_traits = {t for t in cand_provides if t.startswith("trait:")}

    score = 0.0
    for d in deck_list:
        d_provides = provides_set(d)
        d_needs = needs_set(d, score_aspects=score_aspects)
        if score_aspects:
            d_needs = _filter_aspect_needs(d_needs, aspect_pool)
        # Candidate enables what D needs (capped)
        score += w_payoff * min(len(d_needs & cand_provides), cap_per_pair)
        # D enables what candidate needs (capped)
        score += w_enabler * min(len(cand_needs & d_provides), cap_per_pair)
        # Trait-tribal overlap (weaker signal, also capped)
        d_traits = {t for t in d_provides if t.startswith("trait:")}
        score += w_trait_overlap * min(len(cand_traits & d_traits), cap_per_pair)
    return score
