from __future__ import annotations

from fastmcp import FastMCP

from .card_service import CardService
from .deck_service import DeckService
from .game_service import GameService

mcp = FastMCP(
    name="SWU-MCP",
    instructions=(
        "Star Wars Unlimited MCP server. Use these tools to search cards, look up exact printings, "
        "fetch images, upload and playtest decks, validate formats, analyze lists, suggest cards, "
        "and generate first-pass brews."
    ),
)
card_service = CardService()
deck_service = DeckService(card_service)
game_service = GameService(deck_service)


@mcp.tool(description="Search Star Wars Unlimited cards using natural text and optional structured filters.")
def swu_search_cards(
    query: str = "",
    filters: dict[str, str] | None = None,
    limit: int = 10,
    order: str = "name",
    direction: str = "asc",
) -> dict:
    return card_service.search_cards(
        query=query,
        filters=filters,
        limit=limit,
        order=order,
        direction=direction,
    )


@mcp.tool(description="Look up a specific Star Wars Unlimited card by name or set_code/card_number.")
def swu_lookup_card(
    name: str | None = None,
    set_code: str | None = None,
    card_number: str | None = None,
) -> dict:
    return card_service.lookup_card(name=name, set_code=set_code, card_number=card_number)


@mcp.tool(description="Return a random Star Wars Unlimited card from a search result set.")
def swu_random_card(
    query: str = "",
    filters: dict[str, str] | None = None,
) -> dict:
    return card_service.random_card(query=query, filters=filters)


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


@mcp.tool(description="Suggest cards to improve a Star Wars Unlimited deck toward a stated goal.")
def swu_suggest_cards(
    goal: str,
    session_id: str | None = None,
    decklist: str | None = None,
    format_name: str = "premier",
    limit: int = 8,
    target_matchups: list[str] | None = None,
    meta_context: dict | None = None,
) -> dict:
    return deck_service.suggest_cards(
        goal=goal,
        session_id=session_id,
        decklist=decklist,
        format_name=format_name,
        limit=limit,
        target_matchups=target_matchups,
        meta_context=meta_context,
    )


@mcp.tool(description="Generate a first-pass Star Wars Unlimited brew around a theme.")
def swu_generate_deck(
    theme: str,
    format_name: str = "premier",
    primary_aspects: list[str] | None = None,
    leader_names: list[str] | None = None,
    base_name: str | None = None,
    budget: str | None = None,
    target_matchups: list[str] | None = None,
    meta_context: dict | None = None,
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
    )


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
    )


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
