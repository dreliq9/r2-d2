from __future__ import annotations

from typing import Annotated, Any, Optional

from fastmcp import FastMCP
from pydantic import Field

from .ai_brew_service import AIBrewService
from .ai_brew_session import BrewSessionStore
from .card_service import CardService
from .collection_service import CollectionService
from .config import settings
from .deck_service import DeckService
from .game_service import GameService
from .types import (
    BrewCardChange,
    BrewContextFilters,
    BrewContextIntent,
    BrewFormat,
    BrewObjectiveDirections,
    BrewPackage,
    BrewProbabilityCategory,
    BrewRoleTargets,
    BrewSwapSuggestion,
    CardDetail,
    CardSummary,
    SearchFilters,
    SearchOrder,
    SearchResult,
    SortDirection,
    MAX_BREW_CANDIDATE_SWAPS,
    MAX_BREW_MULLIGAN_REDRAWS,
    MAX_BREW_PROBABILITY_CATEGORIES,
    MAX_BREW_SIMULATION_COUNT,
    MAX_BREW_TURN_HORIZON,
    MAX_BREW_TURN_HORIZONS,
)

mcp = FastMCP(
    name="r2-d2",
    instructions=(
        "Star Wars Unlimited MCP server. Use these tools to search cards, look up exact printings, "
        "fetch images, upload and playtest decks, validate formats, analyze lists, suggest cards, "
        "generate first-pass brews, and simulate two-player games with AI opponents. "
        "Also supports a persistent personal collection loaded from a SWUDB CSV export — "
        "pair with only_owned=True on deck generation and suggestions for collection-aware brewing."
    ),
)
card_service = CardService()
collection_service = CollectionService(settings.collection_path)
deck_service = DeckService(card_service, collection_service=collection_service)
game_service = GameService(deck_service)
brew_store = BrewSessionStore(settings.brew_dir)
ai_brew_service = AIBrewService(card_service, collection_service, deck_service, brew_store)


def _dump_brew_card_changes(
    changes: list[BrewCardChange] | None,
) -> list[dict[str, Any]] | None:
    if changes is None:
        return None
    serialized: list[dict[str, Any]] = []
    for change in changes:
        payload = change.model_dump(mode="json")
        payload.pop("card_id", None)
        payload["printing_id"] = change.card_id
        serialized.append(payload)
    return serialized


def _dump_brew_swap_suggestions(
    swaps: list[BrewSwapSuggestion] | None,
) -> list[dict[str, Any]] | None:
    if swaps is None:
        return None
    serialized: list[dict[str, Any]] = []
    for swap in swaps:
        payload = swap.model_dump(mode="json")
        payload["adds"] = _dump_brew_card_changes(swap.adds)
        payload["cuts"] = _dump_brew_card_changes(swap.cuts)
        serialized.append(payload)
    return serialized


# ---------------------------------------------------------------------------
# Card database tools — typed Pydantic surface (v0.3.0)
# ---------------------------------------------------------------------------


@mcp.tool(description=(
    "Search Star Wars Unlimited cards using natural text and optional structured filters. "
    "Pass `query` for free-text matching; use `filters` to constrain by aspect, type, arena, "
    "rarity, set, trait, or numeric stats (cost/power/hp). Returns a typed SearchResult."
))
def swu_search_cards(
    query: Annotated[str, Field(
        description="Free-text search; '*' or empty matches all cards (filtered).",
    )] = "",
    filters: Annotated[Optional[SearchFilters], Field(
        default=None,
        description="Structured filter object — see SearchFilters for valid fields and enums.",
    )] = None,
    limit: Annotated[int, Field(
        ge=1, le=100,
        description="Max cards to return (1-100).",
    )] = 10,
    order: Annotated[SearchOrder, Field(
        description="Sort field for SWU-DB.",
    )] = "name",
    direction: Annotated[SortDirection, Field(
        description="Sort direction.",
    )] = "asc",
) -> SearchResult:
    raw = card_service.search_cards(
        query=query,
        filters=filters.to_legacy_dict() if filters else None,
        limit=limit,
        order=order,
        direction=direction,
    )
    return SearchResult(
        query=raw["query"],
        returned_count=raw["returned_count"],
        total_matches=raw["total_matches"],
        source=raw["source"],
        warning=raw.get("warning"),
        cards=[CardSummary.model_validate(c) for c in raw["cards"]],
    )


@mcp.tool(description=(
    "Look up a specific Star Wars Unlimited card by name or set_code+card_number. "
    "Returns the full CardDetail record."
))
def swu_lookup_card(
    name: Annotated[Optional[str], Field(
        default=None,
        description="Exact or prefix card name. Either this OR (set_code AND card_number) is required.",
    )] = None,
    set_code: Annotated[Optional[str], Field(
        default=None,
        description='Set abbreviation, e.g. "SOR".',
    )] = None,
    card_number: Annotated[Optional[str], Field(
        default=None,
        description='Card number within the set, e.g. "123".',
    )] = None,
) -> CardDetail:
    raw = card_service.lookup_card(name=name, set_code=set_code, card_number=card_number)
    return CardDetail.model_validate(raw)


@mcp.tool(description=(
    "Return a random Star Wars Unlimited card from a search result set."
))
def swu_random_card(
    query: Annotated[str, Field(description="Free-text search to draw a random card from.")] = "",
    filters: Annotated[Optional[SearchFilters], Field(
        default=None,
        description="Optional structured filters.",
    )] = None,
) -> CardSummary:
    raw = card_service.random_card(
        query=query,
        filters=filters.to_legacy_dict() if filters else None,
    )
    return CardSummary.model_validate(raw["card"])


@mcp.tool(description="Return the front or back image URL for a Star Wars Unlimited card.")
def swu_get_image(
    name: str | None = None,
    set_code: str | None = None,
    card_number: str | None = None,
    back_face: bool = False,
) -> dict:
    return card_service.get_image(
        name=name,
        set_code=set_code,
        card_number=card_number,
        back_face=back_face,
    )


# ---------------------------------------------------------------------------
# Deck and game tools — unchanged in v0.3.0; structured-output refactor
# is staged for a follow-up so this PR stays reviewable.
# ---------------------------------------------------------------------------


@mcp.tool(description="Upload a Star Wars Unlimited decklist into a named stateful session.")
def swu_upload_deck(
    decklist: str,
    session_id: str = "default",
    format_name: str = "premier",
    shuffle: bool = True,
    draw_opening_hand: bool = False,
) -> dict:
    return deck_service.upload_deck(
        decklist=decklist,
        session_id=session_id,
        format_name=format_name,
        shuffle=shuffle,
        draw_opening_hand=draw_opening_hand,
    )


@mcp.tool(description="Draw one or more cards from an uploaded deck session.")
def swu_draw_card(session_id: str = "default", count: int = 1) -> dict:
    return deck_service.draw_card(session_id=session_id, count=count)


@mcp.tool(description="View the current hand, resources, and core counters for a deck session.")
def swu_view_hand(session_id: str = "default") -> dict:
    return deck_service.view_hand(session_id=session_id)


@mcp.tool(description="View the current in-play board state, including ground, space, leaders, bases, and resources.")
def swu_view_board(session_id: str = "default") -> dict:
    return deck_service.view_board(session_id=session_id)


@mcp.tool(description="Take a full-hand mulligan in the current deck session.")
def swu_mulligan(session_id: str = "default") -> dict:
    return deck_service.mulligan(session_id=session_id)


@mcp.tool(description="Swap cards between the main deck and sideboard, then reset playtest zones.")
def swu_sideboard(session_id: str = "default", swaps: list[dict] | None = None) -> dict:
    return deck_service.sideboard(session_id=session_id, swaps=swaps)


@mcp.tool(description="Advance the resource phase by readying resources, optionally resourcing a hand card, and drawing for turn.")
def swu_resource_phase(
    session_id: str = "default",
    resource_card: str | None = None,
    draw_for_turn: bool = True,
) -> dict:
    return deck_service.resource_phase(
        session_id=session_id,
        resource_card=resource_card,
        draw_for_turn=draw_for_turn,
    )


@mcp.tool(description="Play or deploy a card from hand, discard, or leader zone into ground, space, or resources.")
def swu_play_card(
    session_id: str = "default",
    card_name: str = "",
    source_zone: str = "hand",
    destination: str = "ground",
    ready: bool = True,
    damage: int = 0,
    experience: int = 0,
    shield: int = 0,
) -> dict:
    return deck_service.play_card(
        session_id=session_id,
        card_name=card_name,
        source_zone=source_zone,
        destination=destination,
        ready=ready,
        damage=damage,
        experience=experience,
        shield=shield,
    )


@mcp.tool(description="Move an existing in-play card or leader/resource between zones such as ground, space, resource, and discard.")
def swu_move_card(
    session_id: str = "default",
    card_name: str = "",
    source_zone: str = "ground",
    destination: str = "discard",
    ready: bool | None = None,
) -> dict:
    return deck_service.move_card(
        session_id=session_id,
        card_name=card_name,
        source_zone=source_zone,
        destination=destination,
        ready=ready,
    )


@mcp.tool(description="Update a card's ready state and counters while it is in play.")
def swu_set_card_state(
    session_id: str = "default",
    card_name: str = "",
    zone: str = "ground",
    ready: bool | None = None,
    damage: int | None = None,
    experience: int | None = None,
    shield: int | None = None,
) -> dict:
    return deck_service.set_card_state(
        session_id=session_id,
        card_name=card_name,
        zone=zone,
        ready=ready,
        damage=damage,
        experience=experience,
        shield=shield,
    )


@mcp.tool(description="Defeat a card from the board or another in-play zone and move it to discard.")
def swu_defeat_card(
    session_id: str = "default",
    card_name: str = "",
    zone: str = "ground",
) -> dict:
    return deck_service.defeat_card(
        session_id=session_id,
        card_name=card_name,
        zone=zone,
    )


@mcp.tool(description="Validate a Star Wars Unlimited deck for Premier or Twin Suns.")
def swu_validate_deck(
    session_id: str | None = None,
    decklist: str | None = None,
    format_name: str = "premier",
) -> dict:
    return deck_service.validate_deck(session_id=session_id, decklist=decklist, format_name=format_name)


@mcp.tool(description="Analyze a Star Wars Unlimited deck's curve, aspects, roles, and synergy.")
def swu_analyze_deck(
    session_id: str | None = None,
    decklist: str | None = None,
    format_name: str = "premier",
    target_matchups: list[str] | None = None,
    meta_context: dict | None = None,
) -> dict:
    return deck_service.analyze_deck(
        session_id=session_id,
        decklist=decklist,
        format_name=format_name,
        target_matchups=target_matchups,
        meta_context=meta_context,
    )


@mcp.tool(description="Suggest cards to improve a Star Wars Unlimited deck toward a stated goal. Set only_owned=True to restrict suggestions to cards in your loaded collection.")
def swu_suggest_cards(
    goal: str,
    session_id: str | None = None,
    decklist: str | None = None,
    format_name: str = "premier",
    limit: int = 8,
    target_matchups: list[str] | None = None,
    meta_context: dict | None = None,
    only_owned: bool = False,
) -> dict:
    return deck_service.suggest_cards(
        goal=goal,
        session_id=session_id,
        decklist=decklist,
        format_name=format_name,
        limit=limit,
        target_matchups=target_matchups,
        meta_context=meta_context,
        only_owned=only_owned,
    )


@mcp.tool(description="Generate a first-pass Star Wars Unlimited brew around a theme. Set only_owned=True to build only with cards in your loaded collection (quantities will be capped by ownership). By default the deck is restricted to on-aspect cards (the aspects granted by the two leaders plus the base); set allow_off_aspect=True to permit off-aspect splashes that cost extra resources. Set target_avg_cost to steer the curve (e.g. 2.5 for an aggressive low-curve deck, 3.5 for midrange); lower = cheaper and faster. When omitted, the format default is used.")
def swu_generate_deck(
    theme: str,
    format_name: str = "premier",
    primary_aspects: list[str] | None = None,
    leader_names: list[str] | None = None,
    base_name: str | None = None,
    budget: str | None = None,
    target_matchups: list[str] | None = None,
    meta_context: dict | None = None,
    only_owned: bool = False,
    allow_off_aspect: bool = False,
    target_avg_cost: float | None = None,
) -> dict:
    return deck_service.generate_deck(
        theme=theme,
        format_name=format_name,
        primary_aspects=primary_aspects,
        leader_names=leader_names,
        base_name=base_name,
        budget=budget,
        target_matchups=target_matchups,
        meta_context=meta_context,
        only_owned=only_owned,
        allow_off_aspect=allow_off_aspect,
        target_avg_cost=target_avg_cost,
    )


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


@mcp.tool(description=(
    "Twin Suns only — fast-score and shortlist legal leader pairs in your "
    "owned pool, then brew and rank finalists by composite score (synergy + "
    "interaction density - off-aspect burden). Use moral='Heroism' or 'Villainy' to "
    "narrow. primary_aspects filters leaders whose aspects intersect the "
    "given list. include_decks=true returns full holoscan lists for the "
    "top_k results. Useful for surfacing leader pairs you wouldn't have "
    "considered manually."
))
def swu_rank_leader_pairs(
    theme: str = "",
    format_name: str = "twin_suns",
    primary_aspects: list[str] | None = None,
    moral: str | None = None,
    only_owned: bool = True,
    top_k: int = 5,
    base_name: str | None = None,
    include_decks: bool = False,
) -> dict:
    return deck_service.rank_leader_pairs(
        theme=theme,
        format_name=format_name,
        primary_aspects=primary_aspects,
        moral=moral,
        only_owned=only_owned,
        top_k=top_k,
        base_name=base_name,
        include_decks=include_decks,
    )


@mcp.tool(description="Import a Star Wars Unlimited card collection from a SWUDB CSV export (columns: Set, CardNumber, Count, IsFoil). Persists to disk. Set merge=True to add to existing collection instead of replacing it.")
def swu_load_collection(csv_path: str, merge: bool = False) -> dict:
    return collection_service.load_csv(csv_path, merge=merge)


@mcp.tool(description="Summarize the loaded Star Wars Unlimited collection — total cards, unique printings, per-set breakdown, and storage path.")
def swu_collection_summary() -> dict:
    return collection_service.summary()


@mcp.tool(description=(
    "Profile the loaded collection for combo-package density. Returns per-package "
    "enabler/payoff counts (Force engine, Indirect damage, When Defeated, Pilot/"
    "Vehicle, Token swarm, Cost reduction, Fortress, Bounty Hunter, Mandalorian) "
    "and flags which are 'live' (≥4 enablers + ≥2 payoffs). "
    "Pass refresh=true to recompute from scratch."
))
def swu_collection_combo_profile(refresh: bool = False) -> dict:
    profile = collection_service.get_combo_profile(refresh=refresh)
    return {
        "card_count": profile.get("card_count", 0),
        "packages": profile["packages"],
    }


@mcp.tool(description="Return how many copies of a specific Star Wars Unlimited printing the user owns. Use set_code and card_number (e.g. LOF 47).")
def swu_owned_count(set_code: str, card_number: str) -> dict:
    count = collection_service.owned_count(set_code=set_code, card_number=card_number)
    return {
        "set_code": set_code.upper(),
        "card_number": str(card_number),
        "owned": count,
    }


@mcp.tool(description="List owned printings from the loaded collection, optionally filtered by set_code. Pass limit=0 for no limit.")
def swu_list_collection(set_code: str | None = None, limit: int = 100) -> dict:
    entries = collection_service.list_entries(set_code=set_code, limit=limit)
    return {
        "set_code": set_code.upper() if set_code else None,
        "limit": limit,
        "count": len(entries),
        "entries": entries,
    }


@mcp.tool(description="Export a deck session or decklist as plain text or JSON.")
def swu_export_deck(
    session_id: str | None = None,
    decklist: str | None = None,
    format_name: str = "premier",
    export_format: str = "plain_text",
) -> dict:
    return deck_service.export_deck(
        session_id=session_id,
        decklist=decklist,
        format_name=format_name,
        export_format=export_format,
    )


@mcp.tool(description="Start a two-player Star Wars Unlimited game between you and Claude.")
def swu_start_game(
    player_decklist: str | None = None,
    opponent_decklist: str | None = None,
    player_theme: str | None = None,
    opponent_theme: str | None = None,
    format_name: str = "premier",
    starting_player: str = "player",
    player_name: str = "You",
    opponent_name: str = "Claude",
    game_id: str | None = None,
    target_matchups: list[str] | None = None,
    meta_context: dict | None = None,
    player_is_ai: bool = False,
) -> dict:
    return game_service.start_game(
        player_decklist=player_decklist,
        opponent_decklist=opponent_decklist,
        player_theme=player_theme,
        opponent_theme=opponent_theme,
        format_name=format_name,
        starting_player=starting_player,
        player_name=player_name,
        opponent_name=opponent_name,
        game_id=game_id,
        target_matchups=target_matchups,
        meta_context=meta_context,
        player_is_ai=player_is_ai,
    )


@mcp.tool(description="Run a full AI-vs-AI game simulation to completion. Both players must be AI (set player_is_ai=true in start_game). Returns winner, base damage breakdown, MVP cards, and full game log.")
def swu_simulate_game(game_id: str, max_turns: int = 50) -> dict:
    return game_service.simulate_game(game_id=game_id, max_turns=max_turns)


@mcp.tool(description="Get the current two-player game state, with hidden information filtered by viewer unless reveal_all is true.")
def swu_get_game_state(game_id: str, viewer: str = "player", reveal_all: bool = False) -> dict:
    return game_service.get_game_state(game_id=game_id, viewer=viewer, reveal_all=reveal_all)


@mcp.tool(description="Return the currently legal actions for the active player in a game.")
def swu_get_legal_actions(game_id: str, player_id: str = "player") -> dict:
    return game_service.get_legal_actions(game_id=game_id, player_id=player_id)


@mcp.tool(description="Take a game action such as resource, play, resolve_effect, pass_priority, deploy_leader, attack, or end_turn.")
def swu_take_game_action(
    game_id: str,
    player_id: str = "player",
    action: str = "",
    card_name: str | None = None,
    target_name: str | None = None,
    source_zone: str | None = None,
    target_zone: str | None = None,
    destination: str | None = None,
    target_player_id: str | None = None,
) -> dict:
    return game_service.take_action(
        game_id=game_id,
        player_id=player_id,
        action=action,
        card_name=card_name,
        target_name=target_name,
        source_zone=source_zone,
        target_zone=target_zone,
        destination=destination,
        target_player_id=target_player_id,
    )


@mcp.tool(description="Let the AI pilot its side for one turn or until it ends the turn.")
def swu_take_ai_turn(game_id: str, player_id: str = "opponent", max_actions: int = 8) -> dict:
    return game_service.take_ai_turn(game_id=game_id, player_id=player_id, max_actions=max_actions)


# ---------------------------------------------------------------------------
# AI-led brew tools — typed delegation surface
# ---------------------------------------------------------------------------


@mcp.tool(description=(
    "Start a durable AI-led brew. The caller AI makes card choices; this tool records the "
    "chosen leaders, base, theme, and constraints without generating a deck automatically."
))
def swu_start_ai_brew(
    format_name: Annotated[BrewFormat, Field(description="Premier or Twin Suns.")],
    leader_names: Annotated[list[str], Field(min_length=1, description="Selected leader names.")],
    base_name: Annotated[str, Field(min_length=1, description="Selected base name.")],
    theme: Annotated[str, Field(min_length=1, description="Caller-selected deck theme.")],
    only_owned: bool = False,
    allow_off_aspect: bool = False,
    target_matchups: list[str] | None = None,
    meta_context: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    return ai_brew_service.start_brew(
        format_name=format_name,
        leader_names=leader_names,
        base_name=base_name,
        theme=theme,
        only_owned=only_owned,
        allow_off_aspect=allow_off_aspect,
        target_matchups=target_matchups,
        meta_context=meta_context,
        session_id=session_id,
    )


@mcp.tool(description=(
    "Read durable AI-brew context and caller-selected candidate filters. The caller AI makes "
    "card choices; this tool only returns evidence and revision state."
))
def swu_get_brew_context(
    session_id: Annotated[str, Field(min_length=1, description="Brew session ID.")],
    intent: Annotated[BrewContextIntent, Field(description="Requested brew context view.")],
    filters: Annotated[BrewContextFilters | None, Field(
        default=None,
        description="Structured caller-selected candidate filters.",
    )] = None,
    cursor: str | None = None,
    limit: Annotated[int, Field(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    return ai_brew_service.get_context(
        session_id=session_id,
        intent=intent,
        filters=filters.model_dump(mode="json") if filters is not None else None,
        cursor=cursor,
        limit=limit,
    )


@mcp.tool(description=(
    "Record explicit AI-brew choices as one immutable revision. The caller AI makes card choices; "
    "this tool never applies evaluator suggestions automatically."
))
def swu_record_brew_decisions(
    session_id: Annotated[str, Field(min_length=1, description="Brew session ID.")],
    expected_revision: Annotated[int, Field(ge=0, description="Current revision required to write.")],
    thesis: str | None = None,
    packages: list[BrewPackage] | None = None,
    role_targets: BrewRoleTargets | None = None,
    additions: list[BrewCardChange] | None = None,
    cuts: list[BrewCardChange] | None = None,
    reservations: list[BrewCardChange] | None = None,
    rejected_cards: list[BrewCardChange] | None = None,
    rationale: str = "",
    evidence_ids: list[str] | None = None,
    advisory_report_id: str | None = None,
    accept_stale_evidence: bool = False,
    restore_revision: Annotated[int | None, Field(ge=0)] = None,
    refresh_collection: bool = False,
) -> dict[str, Any]:
    return ai_brew_service.record_decisions(
        session_id=session_id,
        expected_revision=expected_revision,
        thesis=thesis,
        packages=[package.model_dump(mode="json") for package in packages] if packages is not None else None,
        role_targets=role_targets.model_dump(mode="json") if role_targets is not None else None,
        additions=_dump_brew_card_changes(additions),
        cuts=_dump_brew_card_changes(cuts),
        reservations=_dump_brew_card_changes(reservations),
        rejected_cards=_dump_brew_card_changes(rejected_cards),
        rationale=rationale,
        evidence_ids=evidence_ids,
        advisory_report_id=advisory_report_id,
        accept_stale_evidence=accept_stale_evidence,
        restore_revision=restore_revision,
        refresh_collection=refresh_collection,
    )


@mcp.tool(description=(
    "Evaluate an immutable AI-brew revision with advisory analysis. Suggestions are never applied "
    "automatically; the caller AI must record any card choices in a later revision."
))
def swu_evaluate_ai_brew(
    session_id: Annotated[str, Field(min_length=1, description="Brew session ID.")],
    revision: Annotated[int | None, Field(ge=0)] = None,
    turn_horizons: Annotated[
        list[Annotated[int, Field(ge=0, le=MAX_BREW_TURN_HORIZON)]] | None,
        Field(max_length=MAX_BREW_TURN_HORIZONS),
    ] = None,
    mulligan_redraws: Annotated[int, Field(ge=0, le=MAX_BREW_MULLIGAN_REDRAWS)] = 1,
    simulation_seed: int = 1,
    simulation_count: Annotated[int, Field(ge=1, le=MAX_BREW_SIMULATION_COUNT)] = 1000,
    matchup_inputs: dict[str, Any] | None = None,
    probability_categories: Annotated[
        list[BrewProbabilityCategory] | None,
        Field(max_length=MAX_BREW_PROBABILITY_CATEGORIES),
    ] = None,
    candidate_swaps: Annotated[
        list[BrewSwapSuggestion] | None,
        Field(max_length=MAX_BREW_CANDIDATE_SWAPS),
    ] = None,
    objective_directions: BrewObjectiveDirections | None = None,
) -> dict[str, Any]:
    return ai_brew_service.evaluate_brew(
        session_id=session_id,
        revision=revision,
        turn_horizons=turn_horizons,
        mulligan_redraws=mulligan_redraws,
        simulation_seed=simulation_seed,
        simulation_count=simulation_count,
        matchup_inputs=matchup_inputs,
        probability_categories=[category.model_dump(mode="json") for category in probability_categories]
        if probability_categories is not None
        else None,
        candidate_swaps=_dump_brew_swap_suggestions(candidate_swaps),
        objective_directions=objective_directions.model_dump(mode="json", exclude_none=True)
        if objective_directions is not None
        else None,
    )


@mcp.tool(description=(
    "Finalize the selected AI-brew revision and export it. Finalization fails unless the selected "
    "revision is legal and current; it never accepts suggestions automatically."
))
def swu_finalize_ai_brew(
    session_id: Annotated[str, Field(min_length=1, description="Brew session ID.")],
    expected_revision: Annotated[int, Field(ge=0, description="Current revision required to finalize.")],
) -> dict[str, Any]:
    return ai_brew_service.finalize_brew(
        session_id=session_id,
        expected_revision=expected_revision,
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
