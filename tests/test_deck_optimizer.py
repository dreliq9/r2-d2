from swu_mcp.deck_optimizer import optimize_card_list
from swu_mcp.deck_service import TWIN_SUNS
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
