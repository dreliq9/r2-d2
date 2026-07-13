import json
from pathlib import Path

import pytest

from swu_mcp.card_service import CardService
from swu_mcp.collection_service import CollectionService
from swu_mcp.deck_service import DeckService, TWIN_SUNS


def _collection(path: Path, entries: list[dict[str, object]] | None = None) -> CollectionService:
    path.write_text(
        json.dumps(
            {"entries": entries if entries is not None else [
            {
              "set_code": "LOF",
              "card_number": "016",
              "count": 1,
              "foil_count": 0,
              "name": "Qui-Gon Jinn",
              "subtitle": "Student of the Living Force",
              "type": "Leader"
            },
            {
              "set_code": "LOF",
              "card_number": "007",
              "count": 1,
              "foil_count": 0,
              "name": "Avar Kriss",
              "subtitle": "Marshal of Starlight",
              "type": "Leader"
            }
            ]},
        ),
        encoding="utf-8",
    )
    return CollectionService(path)


class _CatalogCard:
    def __init__(self, card: dict[str, object]) -> None:
        self.card = card

    def to_dict(self) -> dict[str, object]:
        return self.card


def test_requested_twin_suns_leaders_resolve_by_owned_canonical_identity(tmp_path: Path) -> None:
    service = DeckService(CardService(), collection_service=_collection(tmp_path / "collection.json"))
    service._resolve_leader_by_name = lambda _: pytest.fail("owned leader resolution used name lookup")  # type: ignore[method-assign]

    leaders = service._pick_leaders(
        theme="Force replay",
        format_name=TWIN_SUNS,
        leader_names=[
            "Qui-Gon Jinn - Student of the Living Force",
            "Avar Kriss - Marshal of Starlight",
        ],
        only_owned=True,
    )

    assert [leader["display_name"] for leader in leaders] == [
        "Qui-Gon Jinn - Student of the Living Force",
        "Avar Kriss - Marshal of Starlight",
    ]


def test_requested_twin_suns_missing_leader_fails_loudly(tmp_path: Path) -> None:
    service = DeckService(CardService(), collection_service=_collection(tmp_path / "collection.json"))

    with pytest.raises(ValueError, match="Could not resolve requested leader"):
        service.generate_deck(
            theme="Force replay",
            format_name=TWIN_SUNS,
            leader_names=["Missing Leader", "Avar Kriss - Marshal of Starlight"],
            only_owned=True,
        )


def test_requested_base_resolves_to_owned_canonical_printing(tmp_path: Path) -> None:
    requested_base = {
        "name": "Echo Base",
        "display_name": "Echo Base",
        "card_type": "Base",
        "set_code": "SOR",
        "number": "001",
        "lookup_id": "SOR/001",
        "aspects": ["Vigilance"],
    }
    owned_base = {**requested_base, "set_code": "LOF", "number": "010", "lookup_id": "LOF/010"}
    service = DeckService(
        CardService(),
        collection_service=_collection(
            tmp_path / "collection.json",
            entries=[
                {
                    "set_code": "LOF",
                    "card_number": "010",
                    "count": 1,
                    "foil_count": 0,
                    "name": "Echo Base",
                    "type": "Base",
                }
            ],
        ),
    )
    service.card_service.lookup_card = lambda **_: requested_base  # type: ignore[method-assign]
    service.card_service.catalog.lookup = lambda *_: _CatalogCard(owned_base)  # type: ignore[method-assign]

    base = service._pick_base(base_name="Echo Base", aspect_pool=set(), only_owned=True)

    assert base["lookup_id"] == "LOF/010"


def test_requested_unowned_base_fails_loudly(tmp_path: Path) -> None:
    service = DeckService(CardService(), collection_service=_collection(tmp_path / "collection.json"))
    service.card_service.lookup_card = lambda **_: {  # type: ignore[method-assign]
        "name": "Echo Base",
        "display_name": "Echo Base",
        "card_type": "Base",
        "set_code": "SOR",
        "number": "001",
    }

    with pytest.raises(ValueError, match="Could not resolve requested base"):
        service._pick_base(base_name="Echo Base", aspect_pool=set(), only_owned=True)


def test_owned_main_deck_candidate_resolves_to_canonical_printing(tmp_path: Path) -> None:
    candidate = {
        "name": "Rebel Pathfinder",
        "subtitle": "Trailblazer",
        "display_name": "Rebel Pathfinder - Trailblazer",
        "card_type": "Unit",
        "set_code": "SOR",
        "number": "001",
        "lookup_id": "SOR/001",
    }
    owned_candidate = {**candidate, "set_code": "LOF", "number": "020", "lookup_id": "LOF/020"}
    service = DeckService(
        CardService(),
        collection_service=_collection(
            tmp_path / "collection.json",
            entries=[
                {
                    "set_code": "LOF",
                    "card_number": "020",
                    "count": 2,
                    "foil_count": 0,
                    "name": "Rebel Pathfinder",
                    "subtitle": "Trailblazer",
                    "type": "Unit",
                }
            ],
        ),
    )
    service.card_service.catalog.lookup = lambda *_: _CatalogCard(owned_candidate)  # type: ignore[method-assign]

    resolved = service._resolve_owned_printing(candidate)

    assert resolved is not None
    assert resolved["lookup_id"] == "LOF/020"
    assert service._candidate_is_owned(candidate)
    assert service._candidate_owned_count(candidate) == 2


def test_automatic_owned_leader_selection_fails_without_owned_leaders(tmp_path: Path) -> None:
    service = DeckService(CardService(), collection_service=_collection(tmp_path / "collection.json", entries=[]))
    unowned_leader = {
        "name": "Luke Skywalker",
        "display_name": "Luke Skywalker",
        "card_type": "Leader",
        "set_code": "SOR",
        "number": "001",
        "lookup_id": "SOR/001",
    }
    service.card_service.search_cards = lambda **_: {"cards": [unowned_leader]}  # type: ignore[method-assign]
    service._safe_lookup = lambda card: card  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="Could not resolve owned leader"):
        service._pick_leaders(theme="Jedi", format_name=TWIN_SUNS, leader_names=None, only_owned=True)


def test_automatic_owned_leader_selection_uses_collection_without_search(tmp_path: Path) -> None:
    service = DeckService(CardService(), collection_service=_collection(tmp_path / "collection.json"))
    service.card_service.search_cards = lambda **_: pytest.fail("owned leader selection used live search")  # type: ignore[method-assign]

    leaders = service._pick_leaders(
        theme="Force replay",
        format_name=TWIN_SUNS,
        leader_names=None,
        only_owned=True,
    )

    assert {leader["lookup_id"] for leader in leaders} == {"LOF/016", "LOF/007"}


def test_automatic_owned_base_selection_fails_without_owned_base(tmp_path: Path) -> None:
    service = DeckService(CardService(), collection_service=_collection(tmp_path / "collection.json", entries=[]))
    unowned_base = {
        "name": "Echo Base",
        "display_name": "Echo Base",
        "card_type": "Base",
        "set_code": "SOR",
        "number": "001",
    }
    service.card_service.search_cards = lambda **_: {"cards": [unowned_base]}  # type: ignore[method-assign]
    service._safe_lookup = lambda card: card  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="Could not resolve owned base"):
        service._pick_base(base_name=None, aspect_pool=set(), only_owned=True)


def test_requested_twin_suns_duplicate_leaders_fail_loudly(tmp_path: Path) -> None:
    service = DeckService(CardService(), collection_service=_collection(tmp_path / "collection.json"))

    with pytest.raises(ValueError, match="two distinct canonical leaders"):
        service._pick_leaders(
            theme="Force replay",
            format_name=TWIN_SUNS,
            leader_names=[
                "Qui-Gon Jinn - Student of the Living Force",
                "Qui-Gon Jinn - Student of the Living Force",
            ],
            only_owned=True,
        )
