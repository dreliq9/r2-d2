from swu_mcp.archetypes import match_archetype
from swu_mcp.deck_thesis import build_deck_thesis
from swu_mcp.deck_service import TWIN_SUNS


def test_matches_kylo_trench_archetype() -> None:
    leaders = [
        {"display_name": "Kylo Ren - We're Not Done Yet", "name": "Kylo Ren", "subtitle": "We're Not Done Yet"},
        {"display_name": "Admiral Trench - chk-chk-chk-chk", "name": "Admiral Trench", "subtitle": "chk-chk-chk-chk"},
    ]

    archetype = match_archetype(leaders, TWIN_SUNS)

    assert archetype is not None
    assert archetype.archetype_id == "twin-suns-kylo-trench-upgrades"


def test_thesis_includes_archetype_signature_cards() -> None:
    leaders = [
        {"display_name": "Kylo Ren - We're Not Done Yet", "name": "Kylo Ren", "subtitle": "We're Not Done Yet"},
        {"display_name": "Admiral Trench - chk-chk-chk-chk", "name": "Admiral Trench", "subtitle": "chk-chk-chk-chk"},
    ]

    thesis = build_deck_thesis(theme="upgrade discard recursion", leaders=leaders, base=None, format_name=TWIN_SUNS)

    assert "Snapshot Reflexes" in thesis.signature_cards
