from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from .deck_service import (
    DeckService,
    DeckSession,
    GameCardState,
    collect_deck_aspects,
    find_card_index,
    first_arena,
    normalize_format,
    parse_int,
    summarize_for_zone,
    summarize_game_card,
)


TARGETED_EFFECT_KINDS = {
    "damage_unit",
    "damage_base",
    "heal_base",
    "shield_friendly",
    "experience_friendly",
    "attach_upgrade",
}


@dataclass(slots=True)
class PlayerGameState:
    player_id: str
    display_name: str
    deck_session_id: str
    is_ai: bool = False
    resources_played_this_turn: int = 0


@dataclass(slots=True)
class PendingEffect:
    effect_id: str
    controller_id: str
    source_name: str
    trigger: str
    kind: str
    amount: int = 0
    target_scope: str = ""
    text: str = ""
    optional: bool = False
    target_player_id: str | None = None
    target_name: str | None = None
    target_zone: str | None = None
    source_lookup_id: str | None = None


@dataclass(slots=True)
class GameSession:
    game_id: str
    format_name: str
    players: dict[str, PlayerGameState]
    active_player_id: str
    priority_player_id: str
    turn_number: int = 1
    winner: str | None = None
    log: list[str] = field(default_factory=list)
    pending_effects: list[PendingEffect] = field(default_factory=list)
    stack_passes: int = 0
    pending_combat: PendingCombat | None = None


@dataclass(slots=True)
class PendingCombat:
    attacker_player_id: str
    attacker_instance_id: str
    attacker_name: str
    attacker_zone: str
    defender_player_id: str
    target_instance_id: str | None
    target_name: str
    target_zone: str


class GameService:
    def __init__(self, deck_service: DeckService) -> None:
        self.deck_service = deck_service
        self.games: dict[str, GameSession] = {}

    def start_game(
        self,
        *,
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
        meta_context: dict[str, Any] | None = None,
        player_is_ai: bool = False,
    ) -> dict[str, Any]:
        normalized_format = normalize_format(format_name)
        resolved_game_id = game_id or f"game-{uuid4().hex[:8]}"
        player_list = self._resolve_decklist(
            decklist=player_decklist,
            theme=player_theme,
            fallback_theme="heroic midrange pressure",
            format_name=normalized_format,
            target_matchups=target_matchups,
            meta_context=meta_context,
        )
        opponent_list = self._resolve_decklist(
            decklist=opponent_decklist,
            theme=opponent_theme,
            fallback_theme="villainy aggro pressure",
            format_name=normalized_format,
            target_matchups=target_matchups,
            meta_context=meta_context,
        )

        player_session_id = f"{resolved_game_id}:player"
        opponent_session_id = f"{resolved_game_id}:opponent"
        self.deck_service.upload_deck(
            player_list,
            session_id=player_session_id,
            format_name=normalized_format,
            draw_opening_hand=True,
        )
        self.deck_service.upload_deck(
            opponent_list,
            session_id=opponent_session_id,
            format_name=normalized_format,
            draw_opening_hand=True,
        )

        starter = starting_player if starting_player in {"player", "opponent"} else "player"
        game = GameSession(
            game_id=resolved_game_id,
            format_name=normalized_format,
            players={
                "player": PlayerGameState(
                    player_id="player",
                    display_name=player_name,
                    deck_session_id=player_session_id,
                    is_ai=player_is_ai,
                ),
                "opponent": PlayerGameState(
                    player_id="opponent",
                    display_name=opponent_name,
                    deck_session_id=opponent_session_id,
                    is_ai=True,
                ),
            },
            active_player_id=starter,
            priority_player_id=starter,
            log=[f"Game started. {player_name} vs {opponent_name}. {starter} takes the first turn."],
        )
        self.games[resolved_game_id] = game
        return {
            "game_id": resolved_game_id,
            "format": normalized_format,
            "starting_player": starter,
            "state": self.get_game_state(game_id=resolved_game_id, viewer=starter, reveal_all=False),
        }

    def get_game_state(
        self,
        *,
        game_id: str,
        viewer: str = "player",
        reveal_all: bool = False,
    ) -> dict[str, Any]:
        game = self._get_game(game_id)
        players: dict[str, Any] = {}
        for player_id, player_state in game.players.items():
            session = self._deck_session_for(game, player_id)
            snapshot = session.snapshot()
            visible = {
                "display_name": player_state.display_name,
                "hand_count": snapshot["hand_count"],
                "library_count": snapshot["library_count"],
                "discard_count": snapshot["discard_count"],
                "ground_count": snapshot["ground_count"],
                "space_count": snapshot["space_count"],
                "upgrade_count": snapshot["upgrade_count"],
                "resource_count": snapshot["resource_count"],
                "ready_resources": snapshot["ready_resources"],
                "leaders": snapshot["leaders"],
                "base": snapshot["base"],
                "ground_arena": snapshot["ground_arena"],
                "space_arena": snapshot["space_arena"],
                "upgrades": snapshot["upgrades"],
                "resources": snapshot["resources"],
                "bases": snapshot["bases"],
                "deployed_leaders": snapshot["leaders"] if isinstance(snapshot["leaders"], list) else [],
            }
            if reveal_all or viewer == player_id:
                visible["hand"] = snapshot["hand"]
                visible["discard"] = snapshot["discard"]
            players[player_id] = visible

        return {
            "game_id": game.game_id,
            "format": game.format_name,
            "active_player": game.active_player_id,
            "priority_player": game.priority_player_id,
            "turn_number": game.turn_number,
            "winner": game.winner,
            "log": game.log[-12:],
            "pending_combat": (
                {
                    "attacker_player_id": game.pending_combat.attacker_player_id,
                    "attacker_name": game.pending_combat.attacker_name,
                    "attacker_zone": game.pending_combat.attacker_zone,
                    "defender_player_id": game.pending_combat.defender_player_id,
                    "target_name": game.pending_combat.target_name,
                    "target_zone": game.pending_combat.target_zone,
                }
                if game.pending_combat
                else None
            ),
            "pending_effects": [
                {
                    "effect_id": effect.effect_id,
                    "controller_id": effect.controller_id,
                    "source_name": effect.source_name,
                    "trigger": effect.trigger,
                    "kind": effect.kind,
                    "amount": effect.amount,
                    "target_scope": effect.target_scope,
                    "text": effect.text,
                }
                for effect in game.pending_effects
            ],
            "players": players,
        }

    def get_legal_actions(self, *, game_id: str, player_id: str = "player") -> dict[str, Any]:
        game = self._get_game(game_id)
        if game.winner:
            return {
                "game_id": game_id,
                "player_id": player_id,
                "active": False,
                "reason": f"Game over. Winner: {game.winner}.",
                "actions": [],
            }
        if game.pending_effects:
            if player_id != game.priority_player_id:
                return {
                    "game_id": game_id,
                    "player_id": player_id,
                    "active": False,
                    "reason": f"Priority is with {game.priority_player_id}.",
                    "actions": [],
                }
            return {
                "game_id": game_id,
                "player_id": player_id,
                "active": True,
                "reason": "Resolve or pass on the current stack.",
                "actions": self._stack_actions(game, player_id),
            }
        if player_id != game.active_player_id:
            return {
                "game_id": game_id,
                "player_id": player_id,
                "active": False,
                "reason": f"It is {game.active_player_id}'s turn.",
                "actions": [],
            }

        player_state = game.players[player_id]
        session = self._deck_session_for(game, player_id)
        opponent_id = self._other_player_id(player_id)
        opponent_session = self._deck_session_for(game, opponent_id)
        actions: list[dict[str, Any]] = []

        if player_state.resources_played_this_turn == 0:
            for lookup_id in session.hand:
                raw_card = session.card_index[lookup_id]
                actions.append(
                    {
                        "action": "resource",
                        "card_name": raw_card["display_name"],
                    }
                )

        for lookup_id in session.hand:
            raw_card = session.card_index[lookup_id]
            card_type = str(raw_card.get("card_type", ""))
            if card_type not in {"Unit", "Event", "Upgrade"}:
                continue
            total_cost = self._play_cost(session, raw_card)
            if total_cost > self._ready_resource_count(session):
                continue
            actions.extend(
                self._play_action_options(
                    game=game,
                    player_id=player_id,
                    raw_card=raw_card,
                    total_cost=total_cost,
                )
            )

        for leader_state in session.leaders:
            raw_card = session.card_index[leader_state.lookup_id]
            deploy_cost = parse_int(raw_card.get("cost")) or 0
            if leader_state.deployed:
                continue
            if len(session.resources) >= deploy_cost:
                actions.append(
                    {
                        "action": "deploy_leader",
                        "card_name": leader_state.name,
                        "destination": first_arena(raw_card) or "ground",
                        "threshold": deploy_cost,
                    }
                )

        actions.extend(self._attack_actions(session=session, opponent_session=opponent_session))
        actions.append({"action": "end_turn"})
        return {
            "game_id": game_id,
            "player_id": player_id,
            "active": True,
            "actions": actions,
        }

    def take_action(
        self,
        *,
        game_id: str,
        player_id: str = "player",
        action: str,
        card_name: str | None = None,
        target_name: str | None = None,
        source_zone: str | None = None,
        target_zone: str | None = None,
        destination: str | None = None,
        target_player_id: str | None = None,
    ) -> dict[str, Any]:
        game = self._get_game(game_id)
        if game.winner:
            raise ValueError(f"Game already ended. Winner: {game.winner}.")
        if game.pending_effects:
            if player_id != game.priority_player_id:
                raise ValueError(f"It is not {player_id}'s priority.")
        elif player_id != game.active_player_id:
            raise ValueError(f"It is not {player_id}'s turn.")

        normalized_action = action.strip().lower()
        if normalized_action == "resource":
            if not card_name:
                raise ValueError("resource action requires card_name.")
            result = self._take_resource(game, player_id, card_name)
        elif normalized_action == "play":
            if not card_name:
                raise ValueError("play action requires card_name.")
            result = self._play_card(
                game,
                player_id,
                card_name,
                destination=destination,
                target_name=target_name,
                target_zone=target_zone,
                target_player_id=target_player_id,
            )
        elif normalized_action == "deploy_leader":
            if not card_name:
                raise ValueError("deploy_leader action requires card_name.")
            result = self._deploy_leader(game, player_id, card_name)
        elif normalized_action == "attack":
            if not card_name or not target_name or not source_zone or not target_zone:
                raise ValueError("attack action requires card_name, target_name, source_zone, and target_zone.")
            result = self._attack(
                game,
                player_id,
                attacker_name=card_name,
                source_zone=source_zone,
                target_name=target_name,
                target_zone=target_zone,
            )
        elif normalized_action == "end_turn":
            result = self._end_turn(game, player_id)
        elif normalized_action == "resolve_effect":
            result = self.resolve_top_effect(
                game_id=game_id,
                player_id=player_id,
                target_name=target_name,
                target_zone=target_zone,
                target_player_id=target_player_id,
            )
        elif normalized_action == "pass_priority":
            result = self.pass_priority(game_id=game_id, player_id=player_id)
        else:
            raise ValueError(f"Unsupported action: {action}")

        return {
            "game_id": game_id,
            "action": normalized_action,
            "result": result,
            "state": self.get_game_state(game_id=game_id, viewer=player_id, reveal_all=False),
        }

    def resolve_pending_effects(self, *, game_id: str) -> dict[str, Any]:
        game = self._get_game(game_id)
        resolved = self._resolve_pending_effects(game)
        return {
            "game_id": game_id,
            "resolved": resolved,
            "remaining": len(game.pending_effects),
            "state": self.get_game_state(game_id=game_id, viewer=game.active_player_id, reveal_all=False),
        }

    def resolve_top_effect(
        self,
        *,
        game_id: str,
        player_id: str,
        target_name: str | None = None,
        target_zone: str | None = None,
        target_player_id: str | None = None,
    ) -> dict[str, Any]:
        game = self._get_game(game_id)
        if not game.pending_effects:
            raise ValueError("No pending effects on the stack.")
        if player_id != game.priority_player_id:
            raise ValueError(f"It is not {player_id}'s priority.")
        effect = game.pending_effects[-1]
        if effect.controller_id != player_id:
            raise ValueError("Only the effect controller may choose targets for this effect.")
        if effect.kind in TARGETED_EFFECT_KINDS and not effect.target_name:
            if not target_name or not target_zone:
                raise ValueError("This effect requires target_name and target_zone.")
            effect.target_name = target_name
            effect.target_zone = target_zone
            effect.target_player_id = target_player_id or default_target_player(effect)
            game.stack_passes = 0
            game.priority_player_id = self._other_player_id(player_id)
            game.log.append(f"{game.players[player_id].display_name} chose {target_name} for {effect.source_name}.")
            return {
                "game_id": game_id,
                "target_chosen": True,
                "effect_id": effect.effect_id,
                "priority_player": game.priority_player_id,
                "remaining": len(game.pending_effects),
                "state": self.get_game_state(game_id=game_id, viewer=player_id, reveal_all=False),
            }

        resolved = self._resolve_single_top_effect(game)
        return {
            "game_id": game_id,
            "resolved": resolved,
            "remaining": len(game.pending_effects),
            "state": self.get_game_state(game_id=game_id, viewer=player_id, reveal_all=False),
        }

    def pass_priority(self, *, game_id: str, player_id: str) -> dict[str, Any]:
        game = self._get_game(game_id)
        if player_id != game.priority_player_id:
            raise ValueError(f"It is not {player_id}'s priority.")
        if not game.pending_effects:
            raise ValueError("There is no stack to pass on.")
        game.stack_passes += 1
        if game.stack_passes >= 2:
            resolved = self._resolve_single_top_effect(game)
            return {
                "game_id": game_id,
                "passed": True,
                "resolved": resolved,
                "remaining": len(game.pending_effects),
                "state": self.get_game_state(game_id=game_id, viewer=player_id, reveal_all=False),
            }
        game.priority_player_id = self._other_player_id(player_id)
        return {
            "game_id": game_id,
            "passed": True,
            "priority_player": game.priority_player_id,
            "remaining": len(game.pending_effects),
            "state": self.get_game_state(game_id=game_id, viewer=player_id, reveal_all=False),
        }

    def take_ai_turn(self, *, game_id: str, player_id: str = "opponent", max_actions: int = 8) -> dict[str, Any]:
        game = self._get_game(game_id)
        if game.pending_effects:
            if player_id != game.priority_player_id:
                raise ValueError(f"It is not {player_id}'s priority.")
        elif player_id != game.active_player_id:
            raise ValueError(f"It is not {player_id}'s turn.")
        if not game.players[player_id].is_ai:
            raise ValueError(f"{player_id} is not configured as an AI player.")

        executed: list[dict[str, Any]] = []
        for _ in range(max_actions):
            legal = self.get_legal_actions(game_id=game_id, player_id=player_id)
            if not legal.get("active", False):
                break
            action = self._choose_ai_action(game, legal["actions"], player_id)
            if not action:
                break
            result = self.take_action(
                game_id=game_id,
                player_id=player_id,
                action=action["action"],
                card_name=action.get("card_name"),
                target_name=action.get("target_name"),
                source_zone=action.get("source_zone"),
                target_zone=action.get("target_zone"),
                destination=action.get("destination"),
                target_player_id=action.get("target_player_id"),
            )
            executed.append(
                {
                    "action": action["action"],
                    "card_name": action.get("card_name"),
                    "target_name": action.get("target_name"),
                }
            )
            if game.winner:
                break
            if not game.pending_effects and (action["action"] == "end_turn" or game.active_player_id != player_id):
                break

        return {
            "game_id": game_id,
            "player_id": player_id,
            "executed": executed,
            "state": self.get_game_state(game_id=game_id, viewer="player", reveal_all=False),
        }

    def simulate_game(
        self,
        *,
        game_id: str,
        max_turns: int = 50,
    ) -> dict[str, Any]:
        game = self._get_game(game_id)
        if game.winner:
            return {"error": "Game already has a winner.", "winner": game.winner}

        # Ensure both players are AI
        for pid, pstate in game.players.items():
            if not pstate.is_ai:
                raise ValueError(
                    f"{pid} ({pstate.display_name}) is not AI-controlled. "
                    "Set player_is_ai=true when starting the game to simulate."
                )

        # Track per-card damage dealt to bases
        base_damage_by_card: dict[str, dict[str, int]] = {
            "player": {},
            "opponent": {},
        }
        cards_played: dict[str, list[str]] = {"player": [], "opponent": []}
        cards_defeated: dict[str, list[str]] = {"player": [], "opponent": []}
        turn_log: list[dict[str, Any]] = []
        safety_counter = 0
        max_actions_total = max_turns * 30  # hard ceiling

        while not game.winner and game.turn_number <= max_turns * 2:
            safety_counter += 1
            if safety_counter > max_actions_total:
                break

            active = game.active_player_id
            if game.pending_effects:
                active = game.priority_player_id

            log_before = len(game.log)

            # Run one AI turn / priority pass
            try:
                self.take_ai_turn(
                    game_id=game_id,
                    player_id=active,
                    max_actions=12,
                )
            except Exception:
                # If AI gets stuck, try passing or ending turn
                try:
                    self.take_action(
                        game_id=game_id,
                        player_id=active,
                        action="pass_priority" if game.pending_effects else "end_turn",
                    )
                except Exception:
                    break

            # Scan new log entries for stats
            new_entries = game.log[log_before:]
            for entry in new_entries:
                # Track base damage: "X dealt N damage to Y's base with Z"
                dmg_match = re.search(
                    r"dealt (\d+) damage to .+'s base with (.+)\.", entry
                )
                if dmg_match:
                    amount = int(dmg_match.group(1))
                    card = dmg_match.group(2)
                    attacker = "player" if entry.startswith(
                        game.players["player"].display_name
                    ) else "opponent"
                    base_damage_by_card[attacker][card] = (
                        base_damage_by_card[attacker].get(card, 0) + amount
                    )

                # Track cards played
                play_match = re.search(r"played (.+?) for \d+ resources", entry)
                if play_match:
                    card = play_match.group(1)
                    who = "player" if entry.startswith(
                        game.players["player"].display_name
                    ) else "opponent"
                    cards_played[who].append(card)

                # Track defeats
                if "was defeated" in entry or "defeated " in entry.lower():
                    defeat_match = re.search(r"defeated (.+?)[\.\!]", entry, re.IGNORECASE)
                    if defeat_match:
                        card = defeat_match.group(1)
                        # Card belongs to the player who LOST it
                        who = "opponent" if entry.startswith(
                            game.players["player"].display_name
                        ) else "player"
                        cards_defeated[who].append(card)

            # Log turn summary
            if new_entries:
                turn_log.append({
                    "turn": game.turn_number,
                    "active": active,
                    "actions": new_entries,
                })

        # Build final state
        player_session = self._deck_session_for(game, "player")
        opponent_session = self._deck_session_for(game, "opponent")
        p_base_state = player_session.bases[0] if player_session.bases else None
        o_base_state = opponent_session.bases[0] if opponent_session.bases else None

        p_base_hp = int(player_session.card_index[p_base_state.lookup_id]["hp"]) if p_base_state else 0
        o_base_hp = int(opponent_session.card_index[o_base_state.lookup_id]["hp"]) if o_base_state else 0
        p_base_dmg = p_base_state.damage if p_base_state else 0
        o_base_dmg = o_base_state.damage if o_base_state else 0

        # MVP: card that dealt most base damage per side
        def mvp(damage_dict: dict[str, int]) -> dict[str, Any] | None:
            if not damage_dict:
                return None
            top = max(damage_dict, key=damage_dict.get)  # type: ignore[arg-type]
            return {"card": top, "base_damage": damage_dict[top]}

        p_name = game.players["player"].display_name
        o_name = game.players["opponent"].display_name

        return {
            "game_id": game_id,
            "winner": game.winner or "draw (turn limit)",
            "winner_name": (
                game.players[game.winner].display_name if game.winner else None
            ),
            "total_turns": game.turn_number,
            "final_bases": {
                p_name: {
                    "base": p_base_state.name if p_base_state else "?",
                    "hp_remaining": max(0, p_base_hp - p_base_dmg),
                    "hp_total": p_base_hp,
                    "damage_taken": p_base_dmg,
                },
                o_name: {
                    "base": o_base_state.name if o_base_state else "?",
                    "hp_remaining": max(0, o_base_hp - o_base_dmg),
                    "hp_total": o_base_hp,
                    "damage_taken": o_base_dmg,
                },
            },
            "base_damage_by_card": {
                p_name: dict(
                    sorted(
                        base_damage_by_card["player"].items(),
                        key=lambda x: x[1],
                        reverse=True,
                    )
                ),
                o_name: dict(
                    sorted(
                        base_damage_by_card["opponent"].items(),
                        key=lambda x: x[1],
                        reverse=True,
                    )
                ),
            },
            "mvp": {
                p_name: mvp(base_damage_by_card["player"]),
                o_name: mvp(base_damage_by_card["opponent"]),
            },
            "cards_played": {
                p_name: len(cards_played["player"]),
                o_name: len(cards_played["opponent"]),
            },
            "cards_defeated": {
                p_name: len(cards_defeated["player"]),
                o_name: len(cards_defeated["opponent"]),
            },
            "game_log": game.log,
        }

    def _take_resource(self, game: GameSession, player_id: str, card_name: str) -> dict[str, Any]:
        player_state = game.players[player_id]
        if player_state.resources_played_this_turn >= 1:
            raise ValueError("You have already resourced a card this turn.")
        session = self._deck_session_for(game, player_id)
        # Move card from hand to resources directly — do NOT call resource_phase
        # which has the side effect of readying all resources.
        hand_index = find_card_index(session.hand, session.card_index, card_name)
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
        player_state.resources_played_this_turn += 1
        game.log.append(f"{player_state.display_name} resourced {card_name}.")
        return {"resource_card": card_name}

    def _play_card(
        self,
        game: GameSession,
        player_id: str,
        card_name: str,
        *,
        destination: str | None,
        target_name: str | None = None,
        target_zone: str | None = None,
        target_player_id: str | None = None,
    ) -> dict[str, Any]:
        session = self._deck_session_for(game, player_id)
        lookup_id = self._lookup_id_in_hand(session, card_name)
        raw_card = session.card_index[lookup_id]
        total_cost = self._play_cost(session, raw_card)
        self._exhaust_resources(session, total_cost)
        card_type = str(raw_card.get("card_type", ""))

        if card_type == "Unit":
            ready = "Ambush" in set(raw_card.get("keywords", []))
            result = self.deck_service.play_card(
                session_id=session.session_id,
                card_name=card_name,
                source_zone="hand",
                destination=destination or first_arena(raw_card) or "ground",
                ready=ready,
            )
            self._check_for_winner(game)
            game.log.append(
                f"{game.players[player_id].display_name} played {card_name} for {total_cost} resources."
            )
            self._queue_play_effects(
                game,
                controller_id=player_id,
                raw_card=raw_card,
                source_name=card_name,
                source_lookup_id=lookup_id,
                chosen_target_name=target_name,
                chosen_target_zone=target_zone,
                chosen_target_player_id=target_player_id,
            )
            self._start_stack(game, controller_id=player_id)
            return result["played"]

        if card_type == "Event":
            hand_index = self._lookup_id_in_hand_index(session, card_name)
            played_lookup_id = session.hand.pop(hand_index)
            session.discard.append(played_lookup_id)
            game.log.append(
                f"{game.players[player_id].display_name} played event {card_name} for {total_cost} resources."
            )
            self._queue_play_effects(
                game,
                controller_id=player_id,
                raw_card=raw_card,
                source_name=card_name,
                is_event=True,
                source_lookup_id=played_lookup_id,
                chosen_target_name=target_name,
                chosen_target_zone=target_zone,
                chosen_target_player_id=target_player_id,
            )
            self._start_stack(game, controller_id=player_id)
            return summarize_for_zone(raw_card)

        if card_type == "Upgrade":
            target_player = target_player_id or player_id
            if not target_name or not target_zone:
                raise ValueError("Upgrades require target_name and target_zone.")
            target_session = self._deck_session_for(game, target_player)
            target_card = self._targeted_game_card(target_session, target_name=target_name, target_zone=target_zone)
            result = self.deck_service.play_card(
                session_id=session.session_id,
                card_name=card_name,
                source_zone="hand",
                destination="upgrade",
                ready=True,
            )
            upgrade_state = self._find_upgrade_instance(session, result["played"]["name"])
            upgrade_state.attached_to_instance_id = target_card.instance_id
            upgrade_state.attached_to_name = target_card.name
            upgrade_state.arena = target_card.arena or target_zone
            self._apply_upgrade_static_bonus(upgrade_state, target_card, raw_card, target_session)
            game.log.append(
                f"{game.players[player_id].display_name} attached {card_name} to {target_card.name}."
            )
            self._queue_play_effects(
                game,
                controller_id=player_id,
                raw_card=raw_card,
                source_name=card_name,
                source_lookup_id=lookup_id,
                chosen_target_name=target_name,
                chosen_target_zone=target_zone,
                chosen_target_player_id=target_player,
            )
            self._start_stack(game, controller_id=player_id)
            return summarize_game_card(upgrade_state, session.card_index)

        raise ValueError(f"Playing card type '{card_type}' is not supported yet.")

    def _deploy_leader(self, game: GameSession, player_id: str, card_name: str) -> dict[str, Any]:
        session = self._deck_session_for(game, player_id)
        leader_state = self._leader_state(session, card_name)
        raw_card = session.card_index[leader_state.lookup_id]
        threshold = parse_int(raw_card.get("cost")) or 0
        if len(session.resources) < threshold:
            raise ValueError(f"{card_name} requires {threshold} resources to deploy.")

        result = self.deck_service.play_card(
            session_id=session.session_id,
            card_name=card_name,
            source_zone="leader",
            destination=first_arena(raw_card) or "ground",
            ready=True,
        )
        game.log.append(f"{game.players[player_id].display_name} deployed {card_name}.")
        self._queue_play_effects(
            game,
            controller_id=player_id,
            raw_card=raw_card,
            source_name=card_name,
            source_lookup_id=leader_state.lookup_id,
        )
        self._start_stack(game, controller_id=player_id)
        return result["played"]

    def _attack(
        self,
        game: GameSession,
        player_id: str,
        *,
        attacker_name: str,
        source_zone: str,
        target_name: str,
        target_zone: str,
    ) -> dict[str, Any]:
        if game.pending_combat:
            raise ValueError("A combat is already pending resolution.")
        attacker_session = self._deck_session_for(game, player_id)
        defender_id = self._other_player_id(player_id)
        defender_session = self._deck_session_for(game, defender_id)
        attacker = self.deck_service._find_game_card(attacker_session, card_name=attacker_name, zone=source_zone)
        if not attacker.ready:
            raise ValueError(f"{attacker_name} is exhausted and cannot attack.")
        attacker.ready = False
        target = (
            self._base_state(defender_session, target_name)
            if target_zone == "base"
            else self.deck_service._find_game_card(defender_session, card_name=target_name, zone=target_zone)
        )
        game.pending_combat = PendingCombat(
            attacker_player_id=player_id,
            attacker_instance_id=attacker.instance_id,
            attacker_name=attacker.name,
            attacker_zone=source_zone,
            defender_player_id=defender_id,
            target_instance_id=target.instance_id,
            target_name=target.name,
            target_zone=target_zone,
        )
        game.log.append(f"{game.players[player_id].display_name} attacked {target.name} with {attacker_name}.")

        attacker_raw = attacker_session.card_index[attacker.lookup_id]
        self._queue_attack_effects(game, controller_id=player_id, attacker=attacker, raw_card=attacker_raw)
        if game.pending_effects:
            self._start_stack(game, controller_id=player_id)
            return {
                "status": "attack_declared",
                "pending_stack": True,
                "attacker": summarize_game_card(attacker, attacker_session.card_index),
                "target": summarize_game_card(target, defender_session.card_index),
            }
        return self._resolve_pending_combat(game) or {"status": "attack_declared"}

    def _end_turn(self, game: GameSession, player_id: str) -> dict[str, Any]:
        next_player = self._other_player_id(player_id)
        game.active_player_id = next_player
        game.priority_player_id = next_player
        game.players[next_player].resources_played_this_turn = 0
        game.turn_number += 1
        self.deck_service.regroup_phase(
            session_id=game.players[next_player].deck_session_id,
        )
        self.deck_service.resource_phase(
            session_id=game.players[next_player].deck_session_id,
            resource_card=None,
            draw_for_turn=True,
        )
        game.log.append(f"{game.players[player_id].display_name} ended their turn.")
        return {"next_player": next_player}

    def _resolve_decklist(
        self,
        *,
        decklist: str | None,
        theme: str | None,
        fallback_theme: str,
        format_name: str,
        target_matchups: list[str] | None,
        meta_context: dict[str, Any] | None,
    ) -> str:
        if decklist:
            return decklist
        generated = self.deck_service.generate_deck(
            theme=theme or fallback_theme,
            format_name=format_name,
            target_matchups=target_matchups,
            meta_context=meta_context,
        )
        return self._sanitize_generated_decklist(str(generated["deck"]))

    def _sanitize_generated_decklist(self, decklist: str) -> str:
        lines = decklist.splitlines()
        if lines and lines[0].strip().lower() not in {"leaders", "leader"}:
            lines = lines[1:]
        return "\n".join(lines).strip()

    def _get_game(self, game_id: str) -> GameSession:
        game = self.games.get(game_id)
        if not game:
            raise ValueError(f"Unknown game_id: {game_id}")
        return game

    def _deck_session_for(self, game: GameSession, player_id: str) -> DeckSession:
        return self.deck_service._get_session(game.players[player_id].deck_session_id)

    def _other_player_id(self, player_id: str) -> str:
        return "opponent" if player_id == "player" else "player"

    def _lookup_id_in_hand(self, session: DeckSession, card_name: str) -> str:
        return session.hand[self._lookup_id_in_hand_index(session, card_name)]

    def _lookup_id_in_hand_index(self, session: DeckSession, card_name: str) -> int:
        lowered = card_name.strip().lower()
        for index, lookup_id in enumerate(session.hand):
            card = session.card_index[lookup_id]
            if str(card["display_name"]).lower() == lowered:
                return index
        raise ValueError(f"{card_name} is not in hand.")

    def _leader_state(self, session: DeckSession, card_name: str) -> GameCardState:
        lowered = card_name.strip().lower()
        for leader in session.leaders:
            if leader.name.lower() == lowered:
                return leader
        raise ValueError(f"Leader not found: {card_name}")

    def _base_state(self, session: DeckSession, card_name: str) -> GameCardState:
        lowered = card_name.strip().lower()
        for base in session.bases:
            if base.name.lower() == lowered or lowered == "base":
                return base
        raise ValueError(f"Base not found: {card_name}")

    def _ready_resource_count(self, session: DeckSession) -> int:
        return sum(1 for resource in session.resources if resource.ready)

    def _play_cost(self, session: DeckSession, raw_card: dict[str, Any]) -> int:
        base_cost = parse_int(raw_card.get("cost")) or 0
        available_aspects = collect_deck_aspects(session.deck)
        missing_aspects = set(raw_card.get("aspects", [])) - available_aspects
        return base_cost + len(missing_aspects) * 2

    def _exhaust_resources(self, session: DeckSession, cost: int) -> None:
        ready_resources = [resource for resource in session.resources if resource.ready]
        if len(ready_resources) < cost:
            raise ValueError(f"Need {cost} ready resources but only have {len(ready_resources)}.")
        for resource in ready_resources[:cost]:
            resource.ready = False

    def _attack_actions(self, *, session: DeckSession, opponent_session: DeckSession) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        for zone_name, attackers in (("ground", session.ground_arena), ("space", session.space_arena)):
            opposing_zone = opponent_session.ground_arena if zone_name == "ground" else opponent_session.space_arena
            for attacker in attackers:
                if not attacker.ready:
                    continue
                ignores_sentinel = "Saboteur" in self._card_keywords(session, attacker)
                sentinels = [
                    card for card in opposing_zone if "Sentinel" in self._card_keywords(opponent_session, card)
                ]
                targets = (list(opposing_zone) + list(opponent_session.bases)) if (ignores_sentinel or not sentinels) else sentinels
                for target in targets:
                    actions.append(
                        {
                            "action": "attack",
                            "card_name": attacker.name,
                            "source_zone": zone_name,
                            "target_name": target.name,
                            "target_zone": target.zone,
                        }
                    )
        return actions

    def _play_action_options(
        self,
        *,
        game: GameSession,
        player_id: str,
        raw_card: dict[str, Any],
        total_cost: int,
    ) -> list[dict[str, Any]]:
        card_type = str(raw_card.get("card_type", ""))
        display_name = str(raw_card["display_name"])
        if card_type == "Unit":
            return [
                {
                    "action": "play",
                    "card_name": display_name,
                    "card_type": card_type,
                    "cost": total_cost,
                    "destination": first_arena(raw_card) or "ground",
                }
            ]

        if card_type == "Upgrade":
            options: list[dict[str, Any]] = []
            for target_player_id, zone_name, card in self._upgrade_target_candidates(game, player_id, raw_card):
                options.append(
                    {
                        "action": "play",
                        "card_name": display_name,
                        "card_type": card_type,
                        "cost": total_cost,
                        "destination": "upgrade",
                        "target_name": card.name,
                        "target_zone": zone_name,
                        "target_player_id": target_player_id,
                    }
                )
            return options

        base_action = {
            "action": "play",
            "card_name": display_name,
            "card_type": card_type,
            "cost": total_cost,
            "destination": first_arena(raw_card) or "ground",
        }
        effect_specs = parse_effect_specs(str(raw_card.get("front_text") or ""))
        targeted_specs = [effect for effect in effect_specs if effect["kind"] in TARGETED_EFFECT_KINDS]
        if not targeted_specs:
            return [base_action]

        options: list[dict[str, Any]] = []
        for effect in targeted_specs:
            options.extend(self._effect_target_options(game, player_id, effect, base_action))
        return options or [base_action]

    def _upgrade_target_candidates(
        self,
        game: GameSession,
        player_id: str,
        raw_card: dict[str, Any],
    ) -> list[tuple[str, str, GameCardState]]:
        text = str(raw_card.get("front_text") or "").lower()
        attach_line = next((line.strip().lower() for line in text.splitlines() if line.strip().startswith("attach to")), "")
        friendly_only = "friendly" in attach_line and "enemy" not in attach_line
        enemy_only = "enemy" in attach_line
        allow_bases = "base" in attach_line
        allow_units = "unit" in attach_line or not allow_bases
        allow_leaders = allow_units and "non-leader" not in attach_line
        require_vehicle = "vehicle unit" in attach_line and "non-vehicle" not in attach_line and "non vehicle" not in attach_line
        forbid_vehicle = "non-vehicle" in attach_line or "non vehicle" in attach_line

        candidate_players = [player_id, self._other_player_id(player_id)]
        if friendly_only:
            candidate_players = [player_id]
        elif enemy_only:
            candidate_players = [self._other_player_id(player_id)]

        candidates: list[tuple[str, str, GameCardState]] = []
        for target_player_id in candidate_players:
            session = self._deck_session_for(game, target_player_id)
            if allow_units:
                for zone_name, cards in (("ground", session.ground_arena), ("space", session.space_arena)):
                    for card in cards:
                        target_raw = session.card_index[card.lookup_id]
                        traits = set(target_raw.get("traits", []) or [])
                        if require_vehicle and "Vehicle" not in traits:
                            continue
                        if forbid_vehicle and "Vehicle" in traits:
                            continue
                        candidates.append((target_player_id, zone_name, card))
                if allow_leaders:
                    for leader in (leader for leader in session.leaders if leader.deployed):
                        target_raw = session.card_index[leader.lookup_id]
                        traits = set(target_raw.get("traits", []) or [])
                        if require_vehicle and "Vehicle" not in traits:
                            continue
                        if forbid_vehicle and "Vehicle" in traits:
                            continue
                        candidates.append((target_player_id, "leader", leader))
            if allow_bases:
                for base in session.bases:
                    candidates.append((target_player_id, "base", base))
        return candidates

    def _queue_play_effects(
        self,
        game: GameSession,
        *,
        controller_id: str,
        raw_card: dict[str, Any],
        source_name: str,
        is_event: bool = False,
        source_lookup_id: str | None = None,
        chosen_target_name: str | None = None,
        chosen_target_zone: str | None = None,
        chosen_target_player_id: str | None = None,
    ) -> None:
        effect_text = str(raw_card.get("front_text") or "")
        if "Shielded" in set(raw_card.get("keywords", []) or []):
            game.pending_effects.append(
                PendingEffect(
                    effect_id=f"effect-{uuid4().hex[:8]}",
                    controller_id=controller_id,
                    source_name=source_name,
                    trigger="keyword",
                    kind="shield_friendly",
                    amount=1,
                    target_scope="source",
                    text="Shielded",
                    source_lookup_id=source_lookup_id,
                    target_player_id=controller_id,
                )
            )
        if not effect_text:
            return
        if is_event:
            self._queue_effects_from_text(
                game,
                controller_id=controller_id,
                source_name=source_name,
                trigger="event",
                text=effect_text,
                source_lookup_id=source_lookup_id,
                chosen_target_name=chosen_target_name,
                chosen_target_zone=chosen_target_zone,
                chosen_target_player_id=chosen_target_player_id,
            )
            return
        when_played = extract_labeled_text(effect_text, "When Played")
        if when_played:
            self._queue_effects_from_text(
                game,
                controller_id=controller_id,
                source_name=source_name,
                trigger="when_played",
                text=when_played,
                source_lookup_id=source_lookup_id,
                chosen_target_name=chosen_target_name,
                chosen_target_zone=chosen_target_zone,
                chosen_target_player_id=chosen_target_player_id,
            )

    def _queue_attack_effects(
        self,
        game: GameSession,
        *,
        controller_id: str,
        attacker: GameCardState,
        raw_card: dict[str, Any],
    ) -> None:
        on_attack = extract_labeled_text(str(raw_card.get("front_text") or ""), "On Attack")
        if on_attack:
            self._queue_effects_from_text(
                game,
                controller_id=controller_id,
                source_name=attacker.name,
                trigger="on_attack",
                text=on_attack,
            )
        restore_sources = [str(raw_card.get("front_text") or "")] + [
            str(keyword) for keyword in self._card_keywords(self._deck_session_for(game, controller_id), attacker)
        ]
        for source_text in restore_sources:
            match = re.search(r"restore\s*(\d+)", source_text, flags=re.IGNORECASE)
            if not match:
                continue
            amount = int(match.group(1))
            game.pending_effects.append(
                PendingEffect(
                    effect_id=f"effect-{uuid4().hex[:8]}",
                    controller_id=controller_id,
                    source_name=attacker.name,
                    trigger="keyword",
                    kind="heal_base",
                    amount=amount,
                    target_scope="friendly_base",
                    text=f"Restore {amount}",
                )
            )
            break

        for upgrade_controller_id in game.players:
            upgrade_session = self._deck_session_for(game, upgrade_controller_id)
            for upgrade in upgrade_session.upgrades:
                if upgrade.attached_to_instance_id != attacker.instance_id:
                    continue
                upgrade_text = str(upgrade_session.card_index[upgrade.lookup_id].get("front_text") or "")
                upgrade_attack = extract_labeled_text(upgrade_text, "On Attack")
                if not upgrade_attack:
                    continue
                self._queue_effects_from_text(
                    game,
                    controller_id=upgrade_controller_id,
                    source_name=upgrade.name,
                    trigger="on_attack",
                    text=upgrade_attack,
                    source_lookup_id=upgrade.lookup_id,
                )

    def _queue_effects_from_text(
        self,
        game: GameSession,
        *,
        controller_id: str,
        source_name: str,
        trigger: str,
        text: str,
        source_lookup_id: str | None = None,
        chosen_target_name: str | None = None,
        chosen_target_zone: str | None = None,
        chosen_target_player_id: str | None = None,
    ) -> None:
        assigned_choice = False
        for effect in parse_effect_specs(text):
            target_name_for_effect = None
            target_zone_for_effect = None
            target_player_for_effect = None
            if (
                not assigned_choice
                and chosen_target_name
                and chosen_target_zone
                and str(effect["kind"]) in TARGETED_EFFECT_KINDS
            ):
                target_name_for_effect = chosen_target_name
                target_zone_for_effect = chosen_target_zone
                target_player_for_effect = chosen_target_player_id
                assigned_choice = True
            game.pending_effects.append(
                PendingEffect(
                    effect_id=f"effect-{uuid4().hex[:8]}",
                    controller_id=controller_id,
                    source_name=source_name,
                    trigger=trigger,
                    kind=str(effect["kind"]),
                    amount=int(effect.get("amount", 0)),
                    target_scope=str(effect.get("target_scope", "")),
                    text=text,
                    optional=bool(effect.get("optional", False)),
                    source_lookup_id=source_lookup_id,
                    target_name=target_name_for_effect,
                    target_zone=target_zone_for_effect,
                    target_player_id=target_player_for_effect,
                )
            )

    def _start_stack(self, game: GameSession, *, controller_id: str) -> None:
        if not game.pending_effects:
            return
        game.priority_player_id = controller_id
        game.stack_passes = 0

    def _resolve_pending_effects(self, game: GameSession) -> list[dict[str, Any]]:
        resolved: list[dict[str, Any]] = []
        while game.pending_effects and not game.winner:
            resolved_effect = self._resolve_single_top_effect(game)
            if resolved_effect:
                resolved.append(resolved_effect)
        return resolved

    def _resolve_single_top_effect(self, game: GameSession) -> dict[str, Any] | None:
        if not game.pending_effects:
            return None
        effect = game.pending_effects[-1]
        if effect.kind in TARGETED_EFFECT_KINDS and not effect.target_name:
            self._auto_target_effect(game, effect)
        effect = game.pending_effects.pop()
        resolution = self._resolve_effect(game, effect)
        game.stack_passes = 0
        if game.pending_effects:
            game.priority_player_id = game.active_player_id
        else:
            game.priority_player_id = game.active_player_id
            if game.pending_combat and not game.winner:
                combat_resolution = self._resolve_pending_combat(game)
                if combat_resolution:
                    return {"effect": resolution, "combat": combat_resolution} if resolution else {"combat": combat_resolution}
        return resolution

    def _resolve_effect(self, game: GameSession, effect: PendingEffect) -> dict[str, Any] | None:
        controller_session = self._deck_session_for(game, effect.controller_id)
        opponent_id = self._other_player_id(effect.controller_id)
        opponent_session = self._deck_session_for(game, opponent_id)

        if effect.kind == "draw":
            drawn = self.deck_service._draw_cards(controller_session, effect.amount)
            if drawn:
                game.log.append(f"{effect.source_name} resolved and drew {len(drawn)} card(s).")
            return {"effect": effect.kind, "drawn": [card["display_name"] for card in drawn]}

        if effect.kind == "ready_source":
            source = self._source_game_card(controller_session, effect)
            if source:
                source.ready = True
                game.log.append(f"{effect.source_name} readied.")
                return {"effect": effect.kind, "source_name": effect.source_name}
            return None

        if effect.kind == "ready_attached":
            target = self._resolve_effect_target(game, effect) or self._attached_unit_for_effect(game, effect)
            if not target:
                return None
            target.ready = True
            game.log.append(f"{effect.source_name} readied {target.name}.")
            return {"effect": effect.kind, "target": target.name}

        if effect.kind == "damage_unit":
            target = self._resolve_effect_target(game, effect) or self._best_unit_target(opponent_session)
            if not target:
                return None
            target_session = self._target_session_for_effect(game, effect, opponent_session, controller_session)
            self._assign_damage(target, effect.amount)
            self._check_defeat(game, target_session, target)
            game.log.append(f"{effect.source_name} dealt {effect.amount} damage to {target.name}.")
            return {"effect": effect.kind, "target": target.name, "amount": effect.amount}

        if effect.kind == "damage_enemy_ground_all":
            targets = list(opponent_session.ground_arena)
            resolved_targets: list[str] = []
            for target in list(targets):
                self._assign_damage(target, effect.amount)
                self._check_defeat(game, opponent_session, target)
                resolved_targets.append(target.name)
            if resolved_targets:
                game.log.append(
                    f"{effect.source_name} dealt {effect.amount} damage to each defending ground unit."
                )
            return {"effect": effect.kind, "targets": resolved_targets, "amount": effect.amount}

        if effect.kind == "damage_base":
            target_base = self._resolve_effect_target(game, effect) or (opponent_session.bases[0] if opponent_session.bases else None)
            if not target_base:
                return None
            self._assign_damage(target_base, effect.amount)
            self._check_for_winner(game)
            game.log.append(f"{effect.source_name} dealt {effect.amount} damage to the enemy base.")
            return {"effect": effect.kind, "target": target_base.name, "amount": effect.amount}

        if effect.kind == "heal_base":
            target_base = self._resolve_effect_target(game, effect) or (controller_session.bases[0] if controller_session.bases else None)
            if not target_base:
                return None
            target_base.damage = max(0, target_base.damage - effect.amount)
            game.log.append(f"{effect.source_name} healed {effect.amount} damage from the friendly base.")
            return {"effect": effect.kind, "target": target_base.name, "amount": effect.amount}

        if effect.kind == "shield_friendly":
            target = self._resolve_effect_target(game, effect) or self._best_friendly_unit(controller_session)
            if not target:
                return None
            target.shield += 1
            game.log.append(f"{effect.source_name} gave a Shield token to {target.name}.")
            return {"effect": effect.kind, "target": target.name, "amount": 1}

        if effect.kind == "experience_friendly":
            target = self._resolve_effect_target(game, effect) or self._best_friendly_unit(controller_session)
            if not target:
                return None
            target.experience += effect.amount or 1
            game.log.append(f"{effect.source_name} gave {effect.amount or 1} Experience to {target.name}.")
            return {"effect": effect.kind, "target": target.name, "amount": effect.amount or 1}

        if effect.kind == "exhaust_unit":
            target = self._resolve_effect_target(game, effect) or self._best_unit_target(opponent_session)
            if not target:
                return None
            target.ready = False
            game.log.append(f"{effect.source_name} exhausted {target.name}.")
            return {"effect": effect.kind, "target": target.name}

        if effect.kind == "attach_upgrade":
            target = self._resolve_effect_target(game, effect)
            if not target or not effect.source_lookup_id:
                return None
            controller_session = self._deck_session_for(game, effect.controller_id)
            upgrade_state = self._find_upgrade_by_lookup(controller_session, effect.source_lookup_id)
            raw_upgrade = controller_session.card_index[upgrade_state.lookup_id]
            target_session = self._target_session_for_effect(game, effect, opponent_session, controller_session)
            upgrade_state.attached_to_instance_id = target.instance_id
            upgrade_state.attached_to_name = target.name
            upgrade_state.arena = target.arena or target.zone
            self._apply_upgrade_static_bonus(upgrade_state, target, raw_upgrade, target_session)
            game.log.append(f"{effect.source_name} attached to {target.name}.")
            return {"effect": effect.kind, "target": target.name}

        return None

    def _effective_power(self, card_state: GameCardState, raw_card: dict[str, Any]) -> int:
        base_power = parse_int(raw_card.get("power")) or 0
        return base_power + card_state.experience + card_state.power_bonus

    def _effective_hp(self, card_state: GameCardState, raw_card: dict[str, Any]) -> int:
        base_hp = parse_int(raw_card.get("hp")) or 0
        if card_state.zone == "base":
            return base_hp + card_state.hp_bonus
        return base_hp + card_state.experience + card_state.hp_bonus

    def _assign_damage(self, card_state: GameCardState, damage: int) -> None:
        if damage <= 0:
            return
        if card_state.shield > 0:
            card_state.shield -= 1
            return
        card_state.damage += damage

    def _check_defeat(self, game: GameSession, session: DeckSession, card_state: GameCardState) -> None:
        raw_card = session.card_index[card_state.lookup_id]
        if card_state.zone == "discard":
            return
        if card_state.damage < self._effective_hp(card_state, raw_card):
            return

        if raw_card.get("card_type") == "Leader" and card_state.zone in {"ground", "space"}:
            self._detach_upgrades_from_instance(game, card_state.instance_id)
            self.deck_service._remove_state_from_zone(session, card_state, card_state.zone)
            card_state.zone = "leader"
            card_state.ready = False
            card_state.damage = 0
            card_state.shield = 0
            card_state.experience = 0
            card_state.deployed = False
            card_state.arena = first_arena(raw_card)
            session.leaders.append(card_state)
            game.log.append(f"{card_state.name} was defeated and returned to the leader zone exhausted.")
            return

        if card_state.zone in {"ground", "space", "resource"}:
            self._detach_upgrades_from_instance(game, card_state.instance_id)
            self.deck_service._remove_state_from_zone(session, card_state, card_state.zone)
            session.discard.append(card_state.lookup_id)
            card_state.zone = "discard"
            card_state.ready = False
            card_state.arena = None
            game.log.append(f"{card_state.name} was defeated.")

    def _check_for_winner(self, game: GameSession) -> None:
        for player_id, player_state in game.players.items():
            session = self._deck_session_for(game, player_id)
            for base in session.bases:
                raw_card = session.card_index[base.lookup_id]
                if base.damage >= self._effective_hp(base, raw_card):
                    game.winner = self._other_player_id(player_id)
                    game.log.append(f"{game.players[game.winner].display_name} wins by defeating the enemy base.")
                    return

    def _find_card_anywhere(self, session: DeckSession, card_name: str) -> GameCardState | None:
        lowered = card_name.strip().lower()
        for zone in (
            session.ground_arena,
            session.space_arena,
            session.resources,
            session.leaders,
            session.bases,
            session.upgrades,
        ):
            for card in zone:
                if card.name.lower() == lowered:
                    return card
        return None

    def _find_card_by_instance(self, session: DeckSession, instance_id: str) -> GameCardState | None:
        for zone in (
            session.ground_arena,
            session.space_arena,
            session.resources,
            session.leaders,
            session.bases,
            session.upgrades,
        ):
            for card in zone:
                if card.instance_id == instance_id:
                    return card
        return None

    def _source_game_card(self, controller_session: DeckSession, effect: PendingEffect) -> GameCardState | None:
        if effect.source_lookup_id:
            for card in (
                controller_session.ground_arena
                + controller_session.space_arena
                + controller_session.resources
                + controller_session.leaders
                + controller_session.bases
                + controller_session.upgrades
            ):
                if card.lookup_id == effect.source_lookup_id:
                    return card
        return self._find_card_anywhere(controller_session, effect.source_name)

    def _attached_unit_for_effect(self, game: GameSession, effect: PendingEffect) -> GameCardState | None:
        if not effect.source_lookup_id:
            return None
        controller_session = self._deck_session_for(game, effect.controller_id)
        try:
            upgrade = self._find_upgrade_by_lookup(controller_session, effect.source_lookup_id)
        except ValueError:
            return None
        if not upgrade.attached_to_instance_id:
            return None
        for player_id in game.players:
            target = self._find_card_by_instance(self._deck_session_for(game, player_id), upgrade.attached_to_instance_id)
            if target:
                effect.target_player_id = player_id
                return target
        return None

    def _best_unit_target(self, session: DeckSession) -> GameCardState | None:
        units = list(session.ground_arena) + list(session.space_arena)
        units.extend([leader for leader in session.leaders if leader.deployed])
        if not units:
            return None
        return max(
            units,
            key=lambda card: (
                "Sentinel" in self._card_keywords(session, card),
                self._effective_power(card, session.card_index[card.lookup_id]),
                self._effective_hp(card, session.card_index[card.lookup_id]) - card.damage,
            ),
        )

    def _best_friendly_unit(self, session: DeckSession) -> GameCardState | None:
        units = list(session.ground_arena) + list(session.space_arena)
        units.extend([leader for leader in session.leaders if leader.deployed])
        if not units:
            return None
        return max(
            units,
            key=lambda card: (
                self._effective_power(card, session.card_index[card.lookup_id]),
                self._effective_hp(card, session.card_index[card.lookup_id]) - card.damage,
            ),
        )

    def _target_session_for_effect(
        self,
        game: GameSession,
        effect: PendingEffect,
        opponent_session: DeckSession,
        controller_session: DeckSession,
    ) -> DeckSession:
        if effect.target_player_id == effect.controller_id:
            return controller_session
        if effect.target_player_id == self._other_player_id(effect.controller_id):
            return opponent_session
        if effect.target_scope.startswith("friendly") or effect.target_scope in {"source", "attached_unit"}:
            return controller_session
        return opponent_session

    def _resolve_effect_target(self, game: GameSession, effect: PendingEffect) -> GameCardState | None:
        if effect.target_scope == "source":
            controller_session = self._deck_session_for(game, effect.controller_id)
            return self._source_game_card(controller_session, effect)
        if effect.target_scope == "attached_unit":
            return self._attached_unit_for_effect(game, effect)
        if not effect.target_name or not effect.target_zone or not effect.target_player_id:
            return None
        session = self._deck_session_for(game, effect.target_player_id)
        return self._targeted_game_card(session, target_name=effect.target_name, target_zone=effect.target_zone)

    def _stack_actions(self, game: GameSession, player_id: str) -> list[dict[str, Any]]:
        if not game.pending_effects:
            return []
        top = game.pending_effects[-1]
        actions: list[dict[str, Any]] = []
        if (
            top.kind in TARGETED_EFFECT_KINDS
            and not top.target_name
            and top.target_scope not in {"source", "attached_unit"}
            and player_id == top.controller_id
        ):
            actions.extend(
                self._effect_target_options(
                    game,
                    top.controller_id,
                    effect_to_spec(top),
                    {"action": "resolve_effect", "effect_id": top.effect_id, "kind": top.kind},
                )
            )
        actions.append({"action": "pass_priority", "effect_id": top.effect_id})
        return actions

    def _effect_target_options(
        self,
        game: GameSession,
        player_id: str,
        effect_spec: dict[str, Any],
        base_action: dict[str, Any],
    ) -> list[dict[str, Any]]:
        scope = str(effect_spec.get("target_scope", ""))
        options: list[dict[str, Any]] = []
        if scope in {"source", "attached_unit"}:
            return options
        target_player_ids: list[str]
        if scope.startswith("enemy"):
            target_player_ids = [self._other_player_id(player_id)]
        elif scope.startswith("friendly") or scope in {"source", "attached_unit"}:
            target_player_ids = [player_id]
        else:
            target_player_ids = [player_id]

        for target_player_id in target_player_ids:
            session = self._deck_session_for(game, target_player_id)
            if scope in {"enemy_unit", "friendly_unit", "friendly_character", "attached_unit"}:
                cards = list(session.ground_arena) + list(session.space_arena) + [leader for leader in session.leaders if leader.deployed]
                for card in cards:
                    options.append({**base_action, "target_name": card.name, "target_zone": card.zone, "target_player_id": target_player_id})
            elif scope in {"enemy_base", "friendly_base"}:
                for base in session.bases:
                    options.append({**base_action, "target_name": base.name, "target_zone": "base", "target_player_id": target_player_id})
            elif scope == "upgrade_target":
                cards = list(session.ground_arena) + list(session.space_arena) + list(session.bases) + [leader for leader in session.leaders if leader.deployed]
                for card in cards:
                    options.append({**base_action, "target_name": card.name, "target_zone": card.zone, "target_player_id": target_player_id})
        return options

    def _auto_target_effect(self, game: GameSession, effect: PendingEffect) -> None:
        if effect.target_name:
            return
        controller_session = self._deck_session_for(game, effect.controller_id)
        opponent_id = self._other_player_id(effect.controller_id)
        opponent_session = self._deck_session_for(game, opponent_id)

        if effect.target_scope == "source":
            source = self._source_game_card(controller_session, effect)
            if source:
                effect.target_name = source.name
                effect.target_zone = source.zone
                effect.target_player_id = effect.controller_id
            return

        if effect.target_scope == "attached_unit":
            target = self._attached_unit_for_effect(game, effect)
            if target:
                effect.target_name = target.name
                effect.target_zone = target.zone
            return

        if effect.target_scope == "enemy_unit":
            target = self._best_unit_target(opponent_session)
            if target:
                effect.target_name = target.name
                effect.target_zone = target.zone
                effect.target_player_id = opponent_id
            return

        if effect.target_scope in {"friendly_unit", "friendly_character"}:
            target = self._best_friendly_unit(controller_session)
            if target:
                effect.target_name = target.name
                effect.target_zone = target.zone
                effect.target_player_id = effect.controller_id
            return

        if effect.target_scope == "enemy_base" and opponent_session.bases:
            effect.target_name = opponent_session.bases[0].name
            effect.target_zone = "base"
            effect.target_player_id = opponent_id
            return

        if effect.target_scope == "friendly_base" and controller_session.bases:
            effect.target_name = controller_session.bases[0].name
            effect.target_zone = "base"
            effect.target_player_id = effect.controller_id

    def _targeted_game_card(self, session: DeckSession, *, target_name: str, target_zone: str) -> GameCardState:
        if target_zone == "base":
            return self._base_state(session, target_name)
        if target_zone == "leader":
            return self._leader_state(session, target_name)
        return self.deck_service._find_game_card(session, card_name=target_name, zone=target_zone)

    def _find_upgrade_instance(self, session: DeckSession, upgrade_name: str) -> GameCardState:
        lowered = upgrade_name.strip().lower()
        for upgrade in session.upgrades:
            if upgrade.name.lower() == lowered:
                return upgrade
        raise ValueError(f"Upgrade not found: {upgrade_name}")

    def _find_upgrade_by_lookup(self, session: DeckSession, lookup_id: str) -> GameCardState:
        for upgrade in session.upgrades:
            if upgrade.lookup_id == lookup_id:
                return upgrade
        raise ValueError(f"Upgrade lookup not found: {lookup_id}")

    def _apply_upgrade_static_bonus(
        self,
        upgrade_state: GameCardState,
        target_card: GameCardState,
        raw_upgrade: dict[str, Any],
        target_session: DeckSession,
    ) -> None:
        text = str(raw_upgrade.get("front_text") or "")
        power_match = re.search(r"\+(\d+)\s*/\s*\+(\d+)", text)
        if power_match:
            target_card.power_bonus += int(power_match.group(1))
            target_card.hp_bonus += int(power_match.group(2))
        upper_text = text.upper()
        for keyword in ("Sentinel", "Saboteur", "Ambush", "Shielded", "Overwhelm"):
            if f"GAINS {keyword.upper()}" in upper_text and keyword not in target_card.granted_keywords:
                target_card.granted_keywords.append(keyword)

    def _card_keywords(self, session: DeckSession, card_state: GameCardState) -> set[str]:
        raw_keywords = set(session.card_index[card_state.lookup_id].get("keywords", []) or [])
        return raw_keywords | set(card_state.granted_keywords)

    def _choose_ai_action(self, game: GameSession, actions: list[dict[str, Any]], player_id: str) -> dict[str, Any] | None:
        session = self._deck_session_for(game, player_id)

        resolve_actions = [action for action in actions if action["action"] == "resolve_effect"]
        if resolve_actions:
            return max(resolve_actions, key=lambda action: self._effect_target_action_priority(game, player_id, action))

        pass_actions = [action for action in actions if action["action"] == "pass_priority"]
        if pass_actions:
            return pass_actions[0]

        resource_actions = [action for action in actions if action["action"] == "resource"]
        if resource_actions:
            return max(resource_actions, key=lambda action: self._card_priority_for_resource(session, action["card_name"]))

        play_actions = [action for action in actions if action["action"] == "play"]
        if play_actions:
            return min(play_actions, key=lambda action: (action["cost"], 0 if action["card_type"] == "Unit" else 1))

        leader_actions = [action for action in actions if action["action"] == "deploy_leader"]
        if leader_actions:
            return leader_actions[0]

        attack_actions = [action for action in actions if action["action"] == "attack"]
        if attack_actions:
            return max(attack_actions, key=lambda action: self._attack_priority(game, player_id, action))

        end_turn_actions = [action for action in actions if action["action"] == "end_turn"]
        if end_turn_actions:
            return end_turn_actions[0]
        return None

    def _card_priority_for_resource(self, session: DeckSession, card_name: str) -> tuple[int, int]:
        lookup_id = self._lookup_id_in_hand(session, card_name)
        raw_card = session.card_index[lookup_id]
        off_aspect = self._play_cost(session, raw_card) - (parse_int(raw_card.get("cost")) or 0)
        return (off_aspect, parse_int(raw_card.get("cost")) or 0)

    def _attack_priority(self, game: GameSession, player_id: str, action: dict[str, Any]) -> tuple[int, int]:
        defender_session = self._deck_session_for(game, self._other_player_id(player_id))
        target_zone = action["target_zone"]
        target_name = action["target_name"]
        if target_zone == "base":
            base = self._base_state(defender_session, target_name)
            raw = defender_session.card_index[base.lookup_id]
            remaining_hp = self._effective_hp(base, raw) - base.damage
            return (3, -remaining_hp)
        defender = self.deck_service._find_game_card(defender_session, card_name=target_name, zone=target_zone)
        raw = defender_session.card_index[defender.lookup_id]
        remaining_hp = self._effective_hp(defender, raw) - defender.damage
        return (2, -remaining_hp)

    def _effect_target_action_priority(self, game: GameSession, player_id: str, action: dict[str, Any]) -> tuple[int, int]:
        target_zone = action.get("target_zone")
        target_name = action.get("target_name")
        target_player_id = action.get("target_player_id") or self._other_player_id(player_id)
        if not target_zone or not target_name:
            return (0, 0)
        session = self._deck_session_for(game, target_player_id)
        if target_zone == "base":
            base = self._base_state(session, target_name)
            raw = session.card_index[base.lookup_id]
            return (1, -(self._effective_hp(base, raw) - base.damage))
        target = self._targeted_game_card(session, target_name=target_name, target_zone=target_zone)
        raw = session.card_index[target.lookup_id]
        return (
            2 if target_player_id != player_id else 1,
            self._effective_power(target, raw),
        )

    def _resolve_pending_combat(self, game: GameSession) -> dict[str, Any] | None:
        combat = game.pending_combat
        if not combat:
            return None

        attacker_session = self._deck_session_for(game, combat.attacker_player_id)
        defender_session = self._deck_session_for(game, combat.defender_player_id)
        attacker = self._find_card_by_instance(attacker_session, combat.attacker_instance_id)
        if not attacker or attacker.zone not in {"ground", "space"}:
            game.pending_combat = None
            game.log.append("Combat ended with no valid attacker remaining.")
            return {"status": "combat_fizzled"}

        attacker_raw = attacker_session.card_index[attacker.lookup_id]
        attacker_power = self._effective_power(attacker, attacker_raw)

        if combat.target_zone == "base":
            defender_base = self._find_card_by_instance(defender_session, combat.target_instance_id or "") or self._base_state(
                defender_session, combat.target_name
            )
            self._assign_damage(defender_base, attacker_power)
            game.pending_combat = None
            game.log.append(
                f"{game.players[combat.attacker_player_id].display_name} dealt {attacker_power} damage to "
                f"{game.players[combat.defender_player_id].display_name}'s base with {combat.attacker_name}."
            )
            self._check_for_winner(game)
            return {
                "attacker": summarize_game_card(attacker, attacker_session.card_index),
                "target": summarize_game_card(defender_base, defender_session.card_index),
            }

        defender = self._find_card_by_instance(defender_session, combat.target_instance_id or "")
        if not defender or defender.zone == "discard":
            game.pending_combat = None
            game.log.append(f"{combat.target_name} left play before combat damage.")
            return {"status": "combat_fizzled"}

        defender_raw = defender_session.card_index[defender.lookup_id]
        defender_power = self._effective_power(defender, defender_raw)
        defender_remaining_hp = self._effective_hp(defender, defender_raw) - defender.damage
        damage_before = defender.damage
        self._assign_damage(defender, attacker_power)
        self._assign_damage(attacker, defender_power)
        if "Overwhelm" in self._card_keywords(attacker_session, attacker):
            actual_damage = defender.damage - damage_before
            excess = max(0, actual_damage - defender_remaining_hp)
            if excess and defender_session.bases:
                self._assign_damage(defender_session.bases[0], excess)
                game.log.append(f"{combat.attacker_name} dealt {excess} excess damage to the enemy base.")
                self._check_for_winner(game)
        game.pending_combat = None
        self._check_defeat(game, defender_session, defender)
        self._check_defeat(game, attacker_session, attacker)
        self._check_for_winner(game)
        return {
            "attacker": summarize_game_card(attacker, attacker_session.card_index),
            "target": summarize_game_card(defender, defender_session.card_index),
        }

    def _detach_upgrades_from_instance(self, game: GameSession, instance_id: str) -> None:
        for player_id in game.players:
            session = self._deck_session_for(game, player_id)
            for upgrade in list(session.upgrades):
                if upgrade.attached_to_instance_id != instance_id:
                    continue
                session.upgrades.remove(upgrade)
                session.discard.append(upgrade.lookup_id)
                upgrade.zone = "discard"
                upgrade.ready = False
                upgrade.arena = None
                upgrade.attached_to_instance_id = None
                upgrade.attached_to_name = None
                game.log.append(f"{upgrade.name} was discarded because its attached card left play.")


def extract_labeled_text(text: str, label: str) -> str | None:
    match = re.search(rf"{re.escape(label)}:\s*(.+)", text, flags=re.IGNORECASE)
    if not match:
        return None
    extracted = match.group(1).strip()
    return extracted or None


def parse_effect_specs(text: str) -> list[dict[str, Any]]:
    normalized = " ".join(text.replace("\n", " ").split())
    lowered = normalized.lower()
    optional = "you may" in lowered
    effects: list[dict[str, Any]] = []

    for amount in re.findall(r"draw (\d+) cards?", lowered):
        effects.append({"kind": "draw", "amount": int(amount), "target_scope": "self", "optional": optional})
    if "draw a card" in lowered:
        effects.append({"kind": "draw", "amount": 1, "target_scope": "self", "optional": optional})

    for amount in re.findall(r"deal (\d+) damage to (?:a|an|target|enemy)? ?(?:ground |space )?unit", lowered):
        effects.append({"kind": "damage_unit", "amount": int(amount), "target_scope": "enemy_unit", "optional": optional})
    for amount in re.findall(r"deal (\d+) damage to (?:a|an|the|enemy)? ?base", lowered):
        effects.append({"kind": "damage_base", "amount": int(amount), "target_scope": "enemy_base", "optional": optional})
    for amount in re.findall(r"deal (\d+) damage to each ground unit the defending player controls", lowered):
        effects.append({"kind": "damage_enemy_ground_all", "amount": int(amount), "target_scope": "enemy_unit", "optional": optional})

    for amount in re.findall(r"heal (\d+) damage from (?:a|your|the|friendly) base", lowered):
        effects.append({"kind": "heal_base", "amount": int(amount), "target_scope": "friendly_base", "optional": optional})

    if re.search(r"give a shield token to (?:it|him|her|this unit)", lowered):
        effects.append({"kind": "shield_friendly", "amount": 1, "target_scope": "source", "optional": optional})
    if "give a shield token to attached unit" in lowered:
        effects.append({"kind": "shield_friendly", "amount": 1, "target_scope": "attached_unit", "optional": optional})
    if re.search(r"give (?:a |another )?shield token to (?:a|another|a friendly|another friendly) unit", lowered):
        effects.append({"kind": "shield_friendly", "amount": 1, "target_scope": "friendly_unit", "optional": optional})

    if re.search(r"give an? experience token to (?:it|him|her|this unit)", lowered):
        effects.append({"kind": "experience_friendly", "amount": 1, "target_scope": "source", "optional": optional})
    if "give an experience token to attached unit" in lowered:
        effects.append({"kind": "experience_friendly", "amount": 1, "target_scope": "attached_unit", "optional": optional})
    if re.search(r"give (?:an? |another )?experience token to (?:a|another|a friendly|another friendly) unit", lowered):
        effects.append({"kind": "experience_friendly", "amount": 1, "target_scope": "friendly_unit", "optional": optional})

    if "ready this unit" in lowered:
        effects.append({"kind": "ready_source", "amount": 0, "target_scope": "source", "optional": optional})
    if "ready attached unit" in lowered or "attack with attached unit" in lowered:
        effects.append({"kind": "ready_attached", "amount": 0, "target_scope": "attached_unit", "optional": optional})
    if "exhaust attached unit" in lowered:
        effects.append({"kind": "exhaust_unit", "amount": 0, "target_scope": "attached_unit", "optional": optional})
    if re.search(r"exhaust (?:an?|target|enemy) unit", lowered):
        effects.append({"kind": "exhaust_unit", "amount": 0, "target_scope": "enemy_unit", "optional": optional})

    return effects


def default_target_player(effect: PendingEffect) -> str:
    if effect.target_scope.startswith("enemy"):
        return "opponent" if effect.controller_id == "player" else "player"
    return effect.controller_id


def effect_to_spec(effect: PendingEffect) -> dict[str, Any]:
    return {
        "kind": effect.kind,
        "amount": effect.amount,
        "target_scope": effect.target_scope,
        "optional": effect.optional,
    }
