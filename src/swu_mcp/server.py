from __future__ import annotations

from typing import Annotated, Optional

from fastmcp import FastMCP
from pydantic import Field

from .card_service import CardService
from .collection_service import CollectionService
from .config import settings
from .deck_service import DeckService
from .game_service import GameService
from .types import (
    CardDetail,
    CardSummary,
    SearchFilters,
    SearchOrder,
    SearchResult,
    SortDirection,
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


@mcp.tool(description="Generate a first-pass Star Wars Unlimited brew around a theme. Set only_owned=True to build only with cards in your loaded collection (quantities will be capped by ownership).")
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
    )


@mcp.tool(description=(
    "Twin Suns only — brew a deck for every legal leader pairing in your "
    "owned pool and rank them by composite score (synergy + interaction "
    "density - off-aspect burden). Use moral='Heroism' or 'Villainy' to "
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


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
