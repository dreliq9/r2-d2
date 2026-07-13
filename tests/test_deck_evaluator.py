from swu_mcp.deck_evaluator import evaluate_deck_cards
from swu_mcp.deck_thesis import build_deck_thesis
from swu_mcp.deck_service import TWIN_SUNS


def test_evaluator_flags_too_many_upgrades_without_carriers() -> None:
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
        {"display_name": "Carrier", "card_type": "Unit", "cost": 2, "hp": 3, "arenas": ["Ground"]}
    ]

    evaluation = evaluate_deck_cards(cards, thesis)

    assert evaluation.axis_scores["upgrade_carrier_risk"] < 50
    assert any("upgrade carriers" in warning.message for warning in evaluation.warnings)


def test_evaluator_rewards_role_coverage() -> None:
    thesis = build_deck_thesis(
        theme="upgrade discard recursion",
        leaders=[],
        base=None,
        format_name=TWIN_SUNS,
    )
    cards = (
        [{"display_name": f"Carrier {idx}", "card_type": "Unit", "cost": 2, "hp": 4, "arenas": ["Ground"]} for idx in range(14)]
        + [{"display_name": f"Upgrade {idx}", "card_type": "Upgrade", "cost": 1, "front_text": "Attached unit gets +1/+1."} for idx in range(16)]
        + [{"display_name": f"Removal {idx}", "card_type": "Event", "cost": 2, "front_text": "Deal 3 damage to a unit."} for idx in range(8)]
        + [{"display_name": f"Advantage {idx}", "card_type": "Event", "cost": 3, "front_text": "Draw a card."} for idx in range(4)]
        + [{"display_name": f"Enabler {idx}", "card_type": "Event", "cost": 2, "front_text": "Discard a card."} for idx in range(4)]
        + [{"display_name": f"Payoff {idx}", "card_type": "Unit", "cost": 3, "front_text": "When Played: Draw a card."} for idx in range(4)]
        + [{"display_name": f"Stabilizer {idx}", "card_type": "Unit", "cost": 3, "keywords": ["Sentinel"]} for idx in range(6)]
        + [{"display_name": f"Finisher {idx}", "card_type": "Unit", "cost": 5, "power": 3} for idx in range(2)]
    )

    evaluation = evaluate_deck_cards(cards, thesis)

    assert evaluation.axis_scores["role_coverage"] >= 70
    assert evaluation.total_score >= 60


def test_evaluator_penalizes_unknown_cards_without_thesis_roles() -> None:
    thesis = build_deck_thesis(
        theme="unrecognized archetype",
        leaders=[],
        base=None,
        format_name=TWIN_SUNS,
    )

    evaluation = evaluate_deck_cards(
        [{"display_name": "Blank Card", "card_type": "Event", "cost": 3, "front_text": ""}],
        thesis,
    )

    assert evaluation.axis_scores["role_coverage"] < 50
