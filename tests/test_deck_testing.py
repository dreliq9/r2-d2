from types import SimpleNamespace

import pytest

from swu_mcp.deck_testing import goldfish_deck
from swu_mcp.deck_service import PREMIER
from swu_mcp.server import deck_service


def _local_card(name: str, cost: str, lookup_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        to_dict=lambda: {
            "display_name": name,
            "card_type": "Unit",
            "cost": cost,
            "lookup_id": lookup_id,
        }
    )


def _use_local_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deck_service.card_service, "_ensure_local_catalog", lambda: None)
    monkeypatch.setattr(deck_service.card_service.catalog, "is_available", lambda: True)


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
    costs = {
        "Alliance Dispatcher": "1",
        "Battlefield Marine": "2",
        "Yavin 4 Infantry": "5",
    }
    _use_local_catalog(monkeypatch)
    monkeypatch.setattr(
        deck_service.card_service.catalog,
        "lookup_by_name",
        lambda name, **_kwargs: _local_card(name, costs.get(name, "5"), f"SOR/{len(name):03d}"),
    )

    report = goldfish_deck(deck_service, decklist, PREMIER, games=2, seed=1)
    repeated_report = goldfish_deck(deck_service, decklist, PREMIER, games=2, seed=1)

    assert report == repeated_report
    assert report.games == 2
    assert report.average_opening_resources == 6.0
    assert 0 <= report.average_opening_playables <= 6
    assert report.limitations


def test_goldfish_resolves_set_number_main_deck_entries_locally(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_local_catalog(monkeypatch)
    card = _local_card("Resolved Unit", "1", "SOR/001")
    monkeypatch.setattr(
        deck_service.card_service.catalog,
        "lookup",
        lambda set_code, card_number: card if (set_code, card_number) == ("SOR", "001") else None,
    )
    monkeypatch.setattr(
        deck_service.card_service.catalog,
        "lookup_by_name",
        lambda *_args, **_kwargs: pytest.fail("goldfish used name resolution for a set-number entry"),
    )

    report = goldfish_deck(deck_service, "Main Deck\n6 SOR/001", PREMIER, games=1, seed=1)

    assert report.average_opening_playables == 6.0
    assert report.average_opening_resources == 6.0


def test_goldfish_reports_unresolved_cards_as_unknown_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_local_catalog(monkeypatch)
    monkeypatch.setattr(deck_service.card_service.catalog, "lookup", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(deck_service.card_service.catalog, "lookup_by_name", lambda *_args, **_kwargs: None)

    report = goldfish_deck(deck_service, "Main Deck\n6 Missing Card", PREMIER, games=1, seed=1)

    assert report.average_opening_playables == 0.0
    assert report.average_opening_resources == 6.0
    assert "Unresolved main-deck entries remain in the sampled library as unknown-cost cards." in report.limitations


def test_goldfish_requires_at_least_one_game(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_local_catalog(monkeypatch)
    monkeypatch.setattr(
        deck_service.card_service.catalog,
        "lookup_by_name",
        lambda name, **_kwargs: _local_card(name, "1", "SOR/001"),
    )

    with pytest.raises(ValueError, match="games must be at least 1"):
        goldfish_deck(deck_service, "Main Deck\n6 Alliance Dispatcher", PREMIER, games=0)
