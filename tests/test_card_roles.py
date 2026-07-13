from swu_mcp.card_roles import build_role_pools, roles_for_card
from swu_mcp.deck_thesis import build_deck_thesis
from swu_mcp.deck_service import TWIN_SUNS


def _thesis():
    return build_deck_thesis(
        theme="upgrade discard recursion",
        leaders=[
            {
                "display_name": "Kylo Ren - We're Not Done Yet",
                "front_text": "Discard a card from your hand. If you discarded an upgrade this way, draw a card.",
                "back_text": "Play any number of upgrades from your discard pile on this unit.",
                "aspects": ["Vigilance", "Villainy"],
            }
        ],
        base=None,
        format_name=TWIN_SUNS,
    )


def test_upgrade_gets_upgrade_role() -> None:
    profile = roles_for_card(
        {
            "display_name": "Test Saber",
            "card_type": "Upgrade",
            "front_text": "Attached unit gets +2/+0.",
            "cost": 1,
            "traits": ["ITEM", "WEAPON"],
            "keywords": [],
            "arenas": [],
        },
        _thesis(),
    )

    assert "upgrade" in profile.roles
    assert profile.score_by_role["upgrade"] > 0


def test_low_cost_ground_unit_gets_carrier_and_early_roles() -> None:
    profile = roles_for_card(
        {
            "display_name": "Test Carrier",
            "card_type": "Unit",
            "front_text": "",
            "cost": 2,
            "power": 2,
            "hp": 4,
            "traits": ["SITH"],
            "keywords": ["Sentinel"],
            "arenas": ["Ground"],
        },
        _thesis(),
    )

    assert "early_unit" in profile.roles
    assert "upgrade_carrier" in profile.roles
    assert "defensive_stabilizer" in profile.roles


def test_role_pools_group_cards_by_role() -> None:
    cards = [
        {"display_name": "Upgrade", "card_type": "Upgrade", "front_text": "Attached unit gets +1/+1.", "cost": 1},
        {"display_name": "Carrier", "card_type": "Unit", "front_text": "", "cost": 2, "hp": 4, "arenas": ["Ground"]},
    ]

    pools = build_role_pools(cards, _thesis())

    assert "Upgrade" in [card["display_name"] for card in pools["upgrade"]]
    assert "Carrier" in [card["display_name"] for card in pools["upgrade_carrier"]]
