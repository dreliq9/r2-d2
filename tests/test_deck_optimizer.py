from collections import Counter
from pathlib import Path

import pytest

from swu_mcp.card_identity import canonical_key
from swu_mcp.card_service import CardService
from swu_mcp.catalog import LocalCatalog
from swu_mcp.collection_service import CollectionService
from swu_mcp.deck_optimizer import optimize_card_list
from swu_mcp.deck_service import DeckCardEntry, DeckService, ParsedDeck, PREMIER, TWIN_SUNS
from swu_mcp.deck_thesis import build_deck_thesis


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


def test_optimize_deck_rejects_unowned_input_cards(tmp_path: Path) -> None:
    service = DeckService(
        CardService(),
        collection_service=CollectionService(tmp_path / "collection.json"),
    )
    service._resolve_entry = lambda *_args, **_kwargs: {  # type: ignore[method-assign]
        "display_name": "Unowned Unit",
        "name": "Unowned Unit",
        "card_type": "Unit",
        "set_code": "SOR",
        "number": "001",
        "lookup_id": "SOR/001",
        "cost": 2,
    }
    service._candidate_cards = lambda **_kwargs: []  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="unowned"):
        service.optimize_deck(
            decklist={"main_deck": [{"name": "Unowned Unit"}]},
            theme="units",
            only_owned=True,
        )


def test_optimize_deck_uses_local_only_candidate_discovery() -> None:
    service = DeckService(CardService())
    service.card_service.catalog = LocalCatalog(None)
    service.card_service._ensure_local_catalog = lambda: None  # type: ignore[method-assign]
    service.card_service.search_cards = lambda **_kwargs: pytest.fail("optimizer used search_cards")  # type: ignore[method-assign]
    service.resolve_deck = lambda parsed: parsed  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="No local candidate data"):
        service.optimize_deck(decklist={"main_deck": []}, theme="units")


def _unit(
    name: str,
    *,
    display_name: str | None = None,
    number: int,
    cost: int = 2,
    hp: int = 2,
    power: int = 2,
    front_text: str = "",
) -> dict[str, object]:
    return {
        "name": name,
        "display_name": display_name or name,
        "card_type": "Unit",
        "set_code": "TST",
        "number": f"{number:03d}",
        "lookup_id": f"TST/{number:03d}",
        "aspects": ["Command"],
        "arenas": ["Ground"],
        "cost": str(cost),
        "hp": str(hp),
        "power": str(power),
        "front_text": front_text,
    }


def _entry(card: dict[str, object], *, quantity: int = 1) -> DeckCardEntry:
    return DeckCardEntry(
        quantity=quantity,
        name=str(card["display_name"]),
        zone="main_deck",
        set_code=str(card["set_code"]),
        card_number=str(card["number"]),
        card=card,
    )


def _premier_shell(main_deck: list[DeckCardEntry]) -> ParsedDeck:
    return ParsedDeck(
        format_name=PREMIER,
        leaders=[
            DeckCardEntry(
                quantity=1,
                name="Command Leader",
                zone="leaders",
                card={
                    "name": "Command Leader",
                    "display_name": "Command Leader",
                    "card_type": "Leader",
                    "set_code": "TST",
                    "number": "001",
                    "lookup_id": "TST/001",
                    "aspects": ["Command"],
                },
            )
        ],
        bases=[
            DeckCardEntry(
                quantity=1,
                name="Command Base",
                zone="bases",
                card={
                    "name": "Command Base",
                    "display_name": "Command Base",
                    "card_type": "Base",
                    "set_code": "TST",
                    "number": "002",
                    "lookup_id": "TST/002",
                    "aspects": ["Command"],
                },
            )
        ],
        main_deck=main_deck,
    )


def _owned_counts_for(entries: list[DeckCardEntry], *, default: int = 4) -> Counter:
    return Counter({canonical_key(entry.card): default for entry in entries if entry.card})


def test_optimize_deck_rejects_illegal_canonical_duplicate_swap() -> None:
    service = DeckService(CardService())
    existing = _unit(
        "Prepare for Takeoff",
        number=10,
        hp=8,
        front_text="Draw a card. Deal 2 damage to a unit.",
    )
    illegal_candidate = _unit(
        "Prepare For Takeoff",
        display_name="Prepare For Takeoff",
        number=11,
        hp=8,
        front_text="Draw a card. Deal 2 damage to a unit.",
    )
    weak_link = {
        "name": "Weak Link",
        "display_name": "Weak Link",
        "card_type": "Event",
        "set_code": "TST",
        "number": "012",
        "lookup_id": "TST/012",
        "aspects": ["Command"],
        "front_text": "",
    }
    filler = [_entry(_unit(f"Filler Unit {index}", number=100 + index)) for index in range(46)]
    parsed = _premier_shell([
        _entry(weak_link),
        _entry(existing, quantity=3),
        *filler,
    ])
    service.resolve_deck = lambda _parsed: parsed  # type: ignore[method-assign]
    service._candidate_cards = lambda **_kwargs: [illegal_candidate]  # type: ignore[method-assign]

    result = service.optimize_deck(decklist={"main_deck": []}, theme="units", max_iterations=1)

    assert result["swaps"] == []
    assert result["final_score"] == result["initial_score"]


def test_optimize_deck_only_owned_rejects_swap_exceeding_owned_canonical_quantity(tmp_path: Path) -> None:
    service = DeckService(
        CardService(),
        collection_service=CollectionService(tmp_path / "collection.json"),
    )
    owned_card = _unit(
        "Owned Unit",
        number=20,
        hp=8,
        front_text="Draw a card. Deal 2 damage to a unit.",
    )
    illegal_candidate = _unit(
        "owned unit",
        display_name="owned unit",
        number=21,
        hp=8,
        front_text="Draw a card. Deal 2 damage to a unit.",
    )
    weak_link = {
        "name": "Owned Weak Link",
        "display_name": "Owned Weak Link",
        "card_type": "Event",
        "set_code": "TST",
        "number": "022",
        "lookup_id": "TST/022",
        "aspects": ["Command"],
        "front_text": "",
    }
    filler = [_entry(_unit(f"Owned Filler Unit {index}", number=200 + index)) for index in range(48)]
    parsed = _premier_shell([
        _entry(weak_link),
        _entry(owned_card),
        *filler,
    ])
    service.resolve_deck = lambda _parsed: parsed  # type: ignore[method-assign]
    service._resolve_owned_printing = lambda card: card  # type: ignore[method-assign]
    service._candidate_cards = lambda **_kwargs: [illegal_candidate]  # type: ignore[method-assign]
    owned_count_calls = 0

    def owned_counts() -> Counter:
        nonlocal owned_count_calls
        owned_count_calls += 1
        counts = _owned_counts_for(parsed.main_deck)
        counts[canonical_key(owned_card)] = 1
        return counts

    service._owned_counts_by_canonical_key = owned_counts  # type: ignore[method-assign]

    result = service.optimize_deck(
        decklist={"main_deck": []},
        theme="units",
        only_owned=True,
        max_iterations=1,
    )

    assert result["swaps"] == []
    assert result["final_score"] == result["initial_score"]
    assert owned_count_calls == 1


def test_optimize_deck_only_owned_rejects_initial_deck_exceeding_owned_canonical_quantity(tmp_path: Path) -> None:
    service = DeckService(
        CardService(),
        collection_service=CollectionService(tmp_path / "collection.json"),
    )
    owned_card = _unit("Owned Limit Unit", number=30)
    filler = [_entry(_unit(f"Limit Filler Unit {index}", number=300 + index)) for index in range(47)]
    parsed = _premier_shell([
        _entry(owned_card, quantity=3),
        *filler,
    ])
    service.resolve_deck = lambda _parsed: parsed  # type: ignore[method-assign]
    service._resolve_owned_printing = lambda card: card  # type: ignore[method-assign]
    counts = _owned_counts_for(parsed.main_deck)
    counts[canonical_key(owned_card)] = 1
    service._owned_counts_by_canonical_key = lambda: counts  # type: ignore[method-assign]
    service._candidate_cards = lambda **_kwargs: pytest.fail("optimizer searched candidates before owned quantity check")  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="Deck exceeds owned card quantities"):
        service.optimize_deck(
            decklist={"main_deck": []},
            theme="units",
            only_owned=True,
            max_iterations=0,
        )
