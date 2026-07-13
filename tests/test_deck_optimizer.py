from pathlib import Path

import pytest

from swu_mcp.card_service import CardService
from swu_mcp.catalog import LocalCatalog
from swu_mcp.collection_service import CollectionService
from swu_mcp.deck_optimizer import optimize_card_list
from swu_mcp.deck_service import DeckService, TWIN_SUNS
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
