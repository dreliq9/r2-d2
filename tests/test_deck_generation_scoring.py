from swu_mcp.deck_service import (
    TWIN_SUNS,
    generation_score,
    target_packages_for_theme,
    type_target_fractions,
)


def test_upgrade_card_type_matches_upgrade_theme_even_without_text_token() -> None:
    card = {
        "display_name": "Clean Test Attachment",
        "card_type": "Upgrade",
        "front_text": "Attached unit gains Sentinel.",
        "traits": ["ITEM"],
        "keywords": [],
        "aspects": [],
        "rarity": "Common",
        "cost": 1,
    }

    themed = generation_score(
        card=card,
        theme="upgrade recursion",
        aspect_pool=set(),
        budget=None,
        format_name=TWIN_SUNS,
    )
    unthemed = generation_score(
        card=card,
        theme="space control",
        aspect_pool=set(),
        budget=None,
        format_name=TWIN_SUNS,
    )

    assert themed >= unthemed + 6


def test_upgrade_engine_leaders_raise_twin_suns_upgrade_quota() -> None:
    leaders = [
        {
            "front_text": (
                "Action [Exhaust]: Discard a card from your hand. "
                "If you discarded an upgrade this way, draw a card."
            ),
            "back_text": (
                "When Deployed: Play any number of upgrades from your discard pile "
                "on this unit."
            ),
            "epic_action": "",
        },
        {"front_text": "Action [Exhaust]: Discard a card from your hand. Draw a card."},
    ]

    fractions = type_target_fractions(
        theme="discard recursion",
        leaders=leaders,
        format_name=TWIN_SUNS,
    )

    assert fractions["Upgrade"] >= 0.2
    assert fractions["Unit"] <= 0.65


def test_discard_theme_does_not_target_pilot_vehicle_package() -> None:
    packages = target_packages_for_theme("Kylo Ren Admiral Trench discard recursion")

    assert "discard_engine" in packages
    assert "pilot_vehicle" not in packages
