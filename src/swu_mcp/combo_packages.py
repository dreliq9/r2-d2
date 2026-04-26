"""Combo package definitions and tagging.

A combo package is a recognizable archetype with two roles:
- ENABLER: cards that produce the trigger or fuel the engine
- PAYOFF: cards that benefit from the trigger / pay off the engine

Each card can carry zero or more package tags. The brewer reads these tags
and biases scoring when a package is "active" (enough enablers + payoffs
already in the deck/leaders).

Matchers are deliberately conservative — false positives dilute the signal.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable


def _text(card: dict[str, Any]) -> str:
    parts = [
        str(card.get("FrontText") or card.get("front_text") or ""),
        str(card.get("BackText") or card.get("back_text") or ""),
        str(card.get("EpicAction") or card.get("epic_action") or ""),
    ]
    return " ".join(p for p in parts if p)


def _traits(card: dict[str, Any]) -> set[str]:
    raw = card.get("Traits") or card.get("traits") or []
    return {str(t).upper() for t in raw}


def _keywords(card: dict[str, Any]) -> set[str]:
    raw = card.get("Keywords") or card.get("keywords") or []
    return {str(k) for k in raw}


def _ctype(card: dict[str, Any]) -> str:
    return str(card.get("Type") or card.get("card_type") or "")


@dataclass(frozen=True)
class ComboPackage:
    name: str
    description: str
    is_enabler: Callable[[dict[str, Any]], bool]
    is_payoff: Callable[[dict[str, Any]], bool]


# === Force / Jedi engine ============================================
def _force_enabler(c: dict) -> bool:
    return _ctype(c) in ("Unit", "Leader") and (
        "FORCE" in _traits(c) or "JEDI" in _traits(c)
    )


def _force_payoff(c: dict) -> bool:
    txt = _text(c)
    return bool(
        re.search(r"\bForce unit", txt)
        or re.search(r"\bJEDI\b", txt)
        or "Force token" in txt
        or "use the Force" in txt
    )


# === Indirect damage stack ==========================================
def _indirect_enabler(c: dict) -> bool:
    return "deal" in _text(c).lower() and "indirect damage" in _text(c).lower()


def _indirect_payoff(c: dict) -> bool:
    txt = _text(c).lower()
    return (
        "indirect damage you deal" in txt
        or "when indirect damage is dealt" in txt
        or "increased by" in txt and "indirect" in txt
    )


# === When-Defeated value engine =====================================
def _defeat_enabler(c: dict) -> bool:
    return "When Defeated" in _text(c) and _ctype(c) in ("Unit", "Upgrade")


def _defeat_payoff(c: dict) -> bool:
    txt = _text(c).lower()
    return bool(
        re.search(r"defeat (a |an |up to \d+ |\d+ )?(friendly )?units?", txt)
        or "exploit" in txt
        or "sacrifice" in txt
    )


# === Pilot / Vehicle =================================================
def _pilot_enabler(c: dict) -> bool:
    if "PILOT" in _traits(c):
        return True
    if "Piloting" in _keywords(c):
        return True
    return False


def _pilot_payoff(c: dict) -> bool:
    txt = _text(c)
    return bool(
        re.search(r"\bPilot unit", txt)
        or re.search(r"\bVehicle unit", txt)
        or re.search(r"\bPiloting\b", txt)
    )


# === Token / go-wide swarm ==========================================
def _token_enabler(c: dict) -> bool:
    txt = _text(c)
    return bool(
        re.search(r"[Cc]reate (a |an |\d+ |another )?(\w+\s+){0,3}token", txt)
    )


def _token_payoff(c: dict) -> bool:
    txt = _text(c).lower()
    return (
        "for each friendly" in txt
        or "for each other friendly" in txt
        or re.search(r"for each \w+ unit you control", txt) is not None
        or "if you control 6 or more" in txt
    )


# === Cost-reduction cascade =========================================
def _cost_reducer(c: dict) -> bool:
    txt = _text(c).lower()
    return bool(
        re.search(r"costs? \d+ (less|fewer)", txt)
        or "play it for free" in txt
        or "for free" in txt and "play" in txt
    )


def _cost_payoff(c: dict) -> bool:
    cost = card_cost(c)
    return cost is not None and cost >= 5


def card_cost(c: dict) -> int | None:
    raw = c.get("Cost") or c.get("cost")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


# === Sentinel/Restore fortress ======================================
def _fortress_enabler(c: dict) -> bool:
    kw = _keywords(c)
    return bool(kw & {"Sentinel", "Shielded", "Restore", "Grit"})


def _fortress_payoff(c: dict) -> bool:
    txt = _text(c).lower()
    return (
        "shield token" in txt
        or "heal" in txt and "base" in txt
        or "sentinel" in txt
    )


# === Bounty hunter ==================================================
def _bounty_enabler(c: dict) -> bool:
    return "BOUNTY HUNTER" in _traits(c)


def _bounty_payoff(c: dict) -> bool:
    txt = _text(c)
    return "Bounty" in txt or "Bounty Hunter" in txt


# === Mandalorian tribal =============================================
def _mando_enabler(c: dict) -> bool:
    return "MANDALORIAN" in _traits(c)


def _mando_payoff(c: dict) -> bool:
    return "MANDALORIAN" in _text(c).upper()


# === Self-damage / Grit engine =====================================
# Damaging your own units fuels Grit (+1/+0 per damage on it) and other
# damage-payoff effects. Asajj Ventress, certain events, Witch of the Mist
# all hurt your own board on purpose. Neither side names the other —
# Asajj's text doesn't mention Grit.
def _self_damage_enabler(c: dict) -> bool:
    txt = _text(c).lower()
    if not txt:
        return False
    return bool(
        re.search(r"deal \d+ damage to a friendly", txt)
        or re.search(r"deal \d+ damage to a unit you control", txt)
        or re.search(r"deal damage to a friendly", txt)
    )


def _self_damage_payoff(c: dict) -> bool:
    if "Grit" in (c.get("Keywords") or c.get("keywords") or []):
        return True
    txt = _text(c).lower()
    return bool(
        "for each damage" in txt
        or "while this unit is damaged" in txt
        or "while damaged" in txt
        or "if this unit has damage" in txt
    )


# === Attack-trigger engine =========================================
# Cards that grant a "free attack" enable any On-Attack trigger card to
# trigger off-rhythm. Maz Kanata's "When Played: attack with a Force unit
# for free" is the canonical enabler; Niman Strike attacks with an
# exhausted Force unit. Payoff: any "On Attack:" custom trigger text.
def _attack_enabler(c: dict) -> bool:
    txt = _text(c)
    if not txt:
        return False
    if "Ambush" in (c.get("Keywords") or c.get("keywords") or []):
        return True
    return bool(
        re.search(r"\battack with a (friendly )?[\w\- ]*unit", txt, re.IGNORECASE)
        or re.search(r"\bmay attack with", txt, re.IGNORECASE)
        or re.search(r"attack with [\w'\- ]+ even if (it'?s? )?exhausted",
                     txt, re.IGNORECASE)
    )


def _attack_payoff(c: dict) -> bool:
    return "On Attack:" in _text(c)


# === Discard / graveyard engine ====================================
# Cards that discard (yours or opponent's) feed graveyard-recursion and
# discard-payoff effects. Kylo Ren leader discards from hand; Profundity
# discards opponent's hand. Salvage, Luminous Beings, Flight of the
# Inquisitor return cards from the discard pile.
def _discard_enabler(c: dict) -> bool:
    txt = _text(c).lower()
    if not txt:
        return False
    return bool(
        re.search(r"\bdiscard \d+ card", txt)
        or re.search(r"\bdiscard a card", txt)
        or "discard your hand" in txt
        or "discard the top" in txt
    )


def _discard_payoff(c: dict) -> bool:
    txt = _text(c).lower()
    return bool(
        "from your discard pile" in txt
        or "from the discard pile" in txt
    )


# === Replay engine (bounce + When Played re-triggers) ==============
# Implicit synergy that no card calls out by name: cards which return a unit
# to hand / play from discard / let you replay something pair with the rich
# pool of "When Played:" triggers. Qui-Gon's leader ability ("Return a
# friendly non-leader unit to its owner's hand") is the canonical example —
# his text doesn't mention When Played, but every When Played card in the
# deck becomes a re-trigger target.
def _replay_enabler(c: dict) -> bool:
    txt = _text(c)
    if not txt:
        return False
    patterns = [
        r"return a (friendly )?(non-leader )?unit (to|to its)",
        r"return [\w'\-]+ to its owner",
        r"return [\w'\-]+ to your hand",
        r"play a (unit|card) from your (hand|discard)",
        r"play [\w'\- ]+ for free",
        r"put [\w'\- ]+ from your discard pile into play",
    ]
    return any(re.search(p, txt, re.IGNORECASE) for p in patterns)


def _replay_payoff(c: dict) -> bool:
    txt = _text(c)
    # "When Played" is the canonical replay-payoff trigger. We also accept
    # On Attack effects since some bounce/replay enablers also let you attack
    # with the replayed unit. Skip leaders so we don't double-count their
    # Action [Exhaust] abilities as payoffs.
    if c.get("Type") == "Leader" or c.get("card_type") == "Leader":
        return False
    return "When Played:" in txt


# === Exhaust / Ready engine =========================================
# Cards that exhaust units (yours or opponent's) drive an "exhaust pool" that
# other cards consume by readying or by triggering off exhausted targets.
# Ackbar's leader, C-3PO Human-Cyborg Relations, Cat and Mouse, Koiogran Turn
# all live here.
def _exhaust_enabler(c: dict) -> bool:
    txt = _text(c)
    if not txt:
        return False
    # Match effects that *cause* exhaustion of a unit. Skip the cost-syntax
    # "Action [Exhaust]:" used to pay for leader actions (that's the action
    # paying its own cost, not generating an exhaust event on someone else).
    cause_patterns = [
        r"exhaust (a|an|each|all|every|target|another|every) ",
        r"may exhaust (a|an|target) ",
        r"exhaust the defending",
        r"exhaust an enemy",
        r"when [^\.]*?attack[^\.]*?exhaust",
    ]
    return any(re.search(p, txt, re.IGNORECASE) for p in cause_patterns)


def _exhaust_payoff(c: dict) -> bool:
    txt = _text(c).lower()
    if not txt:
        return False
    # Cards that read off exhausted state, or ready exhausted units to recycle
    # the pool, or trigger off attacks/exhaustion.
    payoff_patterns = [
        r"another exhausted",
        r"an exhausted unit",
        r"each exhausted",
        r"if you control [^\.]*exhausted",
        r"for each exhausted",
        r"\bready (a |an |target |that |this |another |the |it\b)",
        r"cannot ready",
        r"can't ready",
    ]
    return any(re.search(p, txt) for p in payoff_patterns)


PACKAGES: list[ComboPackage] = [
    ComboPackage("force_engine",
                 "Force/Jedi attack-and-ready engine",
                 _force_enabler, _force_payoff),
    ComboPackage("indirect_damage",
                 "Stacked indirect damage (Boba/Cunning)",
                 _indirect_enabler, _indirect_payoff),
    ComboPackage("when_defeated",
                 "Death-trigger value loops",
                 _defeat_enabler, _defeat_payoff),
    ComboPackage("pilot_vehicle",
                 "Pilot / Vehicle / Piloting synergy",
                 _pilot_enabler, _pilot_payoff),
    ComboPackage("token_swarm",
                 "Token creation + go-wide payoffs",
                 _token_enabler, _token_payoff),
    ComboPackage("cost_reduction",
                 "Cheap-cast big things",
                 _cost_reducer, _cost_payoff),
    ComboPackage("fortress",
                 "Sentinel/Restore/Grit defense",
                 _fortress_enabler, _fortress_payoff),
    ComboPackage("bounty_hunter",
                 "Bounty Hunter trait synergy",
                 _bounty_enabler, _bounty_payoff),
    ComboPackage("mandalorian",
                 "Mandalorian tribal",
                 _mando_enabler, _mando_payoff),
    ComboPackage("exhaust_engine",
                 "Exhaust units + ready/exhaust payoffs (Ackbar/C-3PO chain)",
                 _exhaust_enabler, _exhaust_payoff),
    ComboPackage("replay_engine",
                 "Bounce/replay enablers + When Played re-triggers (Qui-Gon Jinn)",
                 _replay_enabler, _replay_payoff),
    ComboPackage("self_damage_engine",
                 "Damage your own units to fuel Grit/damage-payoff effects",
                 _self_damage_enabler, _self_damage_payoff),
    ComboPackage("attack_engine",
                 "Free-attack effects + On-Attack triggered abilities",
                 _attack_enabler, _attack_payoff),
    ComboPackage("discard_engine",
                 "Discard sources + discard-pile recursion",
                 _discard_enabler, _discard_payoff),
]


def tag_card(card: dict[str, Any]) -> dict[str, list[str]]:
    """Return {'enables': [...], 'pays_off': [...]} package tags for one card."""
    enables: list[str] = []
    pays_off: list[str] = []
    for pkg in PACKAGES:
        try:
            if pkg.is_enabler(card):
                enables.append(pkg.name)
        except Exception:
            pass
        try:
            if pkg.is_payoff(card):
                pays_off.append(pkg.name)
        except Exception:
            pass
    return {"enables": enables, "pays_off": pays_off}


def profile_collection(cards: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate package counts across a card list. cards = full card detail dicts."""
    counts: dict[str, dict[str, int]] = {
        pkg.name: {"enablers": 0, "payoffs": 0} for pkg in PACKAGES
    }
    per_card: dict[str, dict[str, list[str]]] = {}
    for card in cards:
        tags = tag_card(card)
        if not (tags["enables"] or tags["pays_off"]):
            continue
        # Use lookup_id or fallback to set/number
        key = (
            str(card.get("lookup_id"))
            if card.get("lookup_id")
            else f"{card.get('Set') or card.get('set_code')}/"
                 f"{str(card.get('Number') or card.get('card_number') or '').zfill(3)}"
        )
        per_card[key] = tags
        for pkg_name in tags["enables"]:
            counts[pkg_name]["enablers"] += 1
        for pkg_name in tags["pays_off"]:
            counts[pkg_name]["payoffs"] += 1

    # Score: a package is "live" if it has enablers AND payoffs
    summary = []
    for pkg in PACKAGES:
        cnt = counts[pkg.name]
        live = cnt["enablers"] >= 4 and cnt["payoffs"] >= 2
        summary.append({
            "package": pkg.name,
            "description": pkg.description,
            "enablers": cnt["enablers"],
            "payoffs": cnt["payoffs"],
            "live": live,
        })
    summary.sort(key=lambda s: -(s["enablers"] + s["payoffs"]))
    return {"packages": summary, "tags_by_card": per_card}
