from types import SimpleNamespace

import pytest

from swu_mcp.deck_testing import goldfish_deck
from swu_mcp.deck_service import PREMIER
from swu_mcp.server import deck_service


def test_goldfish_report_is_seeded_and_includes_limitations(monkeypatch: pytest.MonkeyPatch) -> None:
    decklist = """
    Leaders
    1 Luke Skywalker - Faithful Friend

    Base
    1 Command Center - Lothal

    Main Deck
    3 Alliance Dispatcher
    3 Battlefield Marine
    3 Yavin 4 Infantry
    3 Wing Leader
    3 Open Fire
    3 Resupply
    3 Bright Hope - The Last Transport
    3 Echo Base Defender
    3 General Dodonna - Massassi Group Commander
    3 Rebel Assault
    3 Medal Ceremony
    3 Snowspeeder
    3 Rogue Squadron Skirmisher
    3 Frontline Shuttle
    3 Fleet Lieutenant
    3 Strike True
    2 Home One - Alliance Flagship
    """

    local_card = {
        "display_name": "Alliance Dispatcher",
        "card_type": "Unit",
        "cost": "1",
    }
    monkeypatch.setattr(deck_service.card_service, "_ensure_local_catalog", lambda: None)
    monkeypatch.setattr(deck_service.card_service.catalog, "is_available", lambda: True)
    monkeypatch.setattr(
        deck_service.card_service.catalog,
        "lookup_by_name",
        lambda *_args, **_kwargs: SimpleNamespace(to_dict=lambda: local_card),
    )

    report = goldfish_deck(deck_service, decklist, PREMIER, games=2, seed=1)

    assert report.games == 2
    assert 0 <= report.average_opening_playables
    assert report.limitations
