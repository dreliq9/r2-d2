from swu_mcp.combo_packages import tag_card


def test_non_vehicle_attach_text_is_not_a_vehicle_payoff() -> None:
    card = {
        "Type": "Upgrade",
        "FrontText": "Attach to a non-Vehicle unit. Attached unit gains Saboteur.",
        "Traits": ["ITEM"],
        "Keywords": [],
    }

    assert "pilot_vehicle" not in tag_card(card)["pays_off"]


def test_vehicle_unit_text_is_still_a_vehicle_payoff() -> None:
    card = {
        "Type": "Event",
        "FrontText": "Choose a friendly Vehicle unit. It gets +2/+0 for this attack.",
        "Traits": ["TACTIC"],
        "Keywords": [],
    }

    assert "pilot_vehicle" in tag_card(card)["pays_off"]
