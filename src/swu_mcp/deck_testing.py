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
    if games < 1:
        raise ValueError("games must be at least 1")
    deck_service.card_service._ensure_local_catalog()
    if not deck_service.card_service.catalog.is_available():
        raise RuntimeError("Goldfish reports require a local card catalog.")
    parsed = deck_service.parse_decklist(decklist=decklist, format_name=format_name)
    library: list[dict] = []
    unresolved_entries = 0
    for entry in parsed.main_deck:
        card = entry.card
        if card is None and entry.set_code and entry.card_number:
            local_card = deck_service.card_service.catalog.lookup(entry.set_code, entry.card_number)
            card = local_card.to_dict() if local_card else None
        if card is None and entry.name.strip():
            local_card = deck_service.card_service.catalog.lookup_by_name(
                entry.name,
                exclude_types={"Leader", "Base"},
            )
            card = local_card.to_dict() if local_card else None
        if card is None:
            unresolved_entries += 1
            card = {"cost": None}
        library.extend([card] * entry.quantity)

    rng = random.Random(seed)
    playable_counts: list[int] = []
    resource_counts: list[int] = []
    for _ in range(games):
        shuffled = list(library)
        rng.shuffle(shuffled)
        hand = shuffled[:6]
        playable_counts.append(
            sum(1 for card in hand if (cost := parse_int(card.get("cost"))) is not None and cost <= 2)
        )
        resource_counts.append(len(hand))
    limitations = (
        "Goldfish report checks opening hand texture only.",
        "Current simulator does not fully model every nested optional trigger.",
    )
    if unresolved_entries:
        limitations += ("Unresolved main-deck entries remain in the sampled library as unknown-cost cards.",)

    return GoldfishReport(
        games=games,
        average_opening_playables=round(sum(playable_counts) / max(games, 1), 2),
        average_opening_resources=round(sum(resource_counts) / max(games, 1), 2),
        limitations=limitations,
    )
