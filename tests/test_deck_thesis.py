from swu_mcp.deck_thesis import build_deck_thesis
from swu_mcp.deck_service import TWIN_SUNS


def test_kylo_trench_thesis_sets_upgrade_discard_roles() -> None:
    leaders = [
        {
            "display_name": "Kylo Ren - We're Not Done Yet",
            "front_text": "Action [Exhaust]: Discard a card from your hand. If you discarded an upgrade this way, draw a card.",
            "back_text": "When Deployed: Play any number of upgrades from your discard pile on this unit.",
            "aspects": ["Vigilance", "Villainy"],
        },
        {
            "display_name": "Admiral Trench - chk-chk-chk-chk",
            "front_text": "Action [Exhaust]: Discard a card from your hand. Draw a card.",
            "aspects": ["Cunning", "Villainy"],
        },
    ]

    thesis = build_deck_thesis(
        theme="upgrade discard recursion",
        leaders=leaders,
        base={"display_name": "Data Vault - Scarif", "aspects": ["Command"]},
        format_name=TWIN_SUNS,
    )

    assert "discard_engine" in thesis.target_packages
    assert thesis.role_targets["upgrade"].minimum >= 14
    assert thesis.role_targets["upgrade_carrier"].minimum >= 10
    assert thesis.role_targets["defensive_stabilizer"].minimum >= 6


def test_vehicle_theme_sets_vehicle_roles_without_forcing_upgrade_engine() -> None:
    thesis = build_deck_thesis(
        theme="vehicle pilot starfighter aggro",
        leaders=[],
        base=None,
        format_name=TWIN_SUNS,
    )

    assert "pilot_vehicle" in thesis.target_packages
    assert thesis.role_targets["engine_enabler"].minimum >= 8
    assert thesis.role_targets["upgrade"].minimum < 14


def test_build_deck_thesis_accepts_the_specified_positional_signature() -> None:
    thesis = build_deck_thesis(
        "vehicle pilot",
        [],
        None,
        TWIN_SUNS,
    )

    assert thesis.format_name == TWIN_SUNS


def test_unknown_theme_keeps_baseline_heuristic_targets() -> None:
    thesis = build_deck_thesis(
        theme="unrecognized archetype",
        leaders=[],
        base=None,
        format_name=TWIN_SUNS,
    )

    assert thesis.role_targets
    assert thesis.role_targets["early_unit"].minimum > 0
    assert not thesis.target_packages
