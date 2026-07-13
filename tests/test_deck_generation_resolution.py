import json
from pathlib import Path

import pytest

from swu_mcp.card_service import CardService
from swu_mcp.catalog import LocalCatalog
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


def _local_catalog(path: Path, cards: list[dict[str, object]]) -> LocalCatalog:
    path.write_text(json.dumps(cards), encoding="utf-8")
    return LocalCatalog(str(path))


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


def test_normal_automatic_selection_uses_local_catalog_without_search(tmp_path: Path) -> None:
    catalog_path = tmp_path / "cards.json"
    catalog_path.write_text(
        json.dumps(
            [
                {
                    "Set": "LOF",
                    "Number": "016",
                    "Name": "Qui-Gon Jinn",
                    "Subtitle": "Student of the Living Force",
                    "Type": "Leader",
                    "Aspects": ["Vigilance"],
                },
                {
                    "Set": "LOF",
                    "Number": "007",
                    "Name": "Avar Kriss",
                    "Subtitle": "Marshal of Starlight",
                    "Type": "Leader",
                    "Aspects": ["Vigilance"],
                },
                {
                    "Set": "LOF",
                    "Number": "010",
                    "Name": "Echo Base",
                    "Type": "Base",
                    "Aspects": ["Vigilance"],
                    "HP": "30",
                },
            ]
        ),
        encoding="utf-8",
    )
    service = DeckService(CardService())
    service.card_service.catalog = LocalCatalog(str(catalog_path))
    service.card_service.search_cards = lambda **_: pytest.fail("normal selection used live search")  # type: ignore[method-assign]

    leaders = service._pick_leaders(
        theme="Force replay",
        format_name=TWIN_SUNS,
        leader_names=None,
    )
    base = service._pick_base(base_name=None, aspect_pool=set())

    assert {leader["lookup_id"] for leader in leaders} == {"LOF/016", "LOF/007"}
    assert base["lookup_id"] == "LOF/010"


def test_requested_normal_leader_uses_local_catalog_without_search(tmp_path: Path) -> None:
    service = DeckService(CardService())
    service.card_service.catalog = _local_catalog(
        tmp_path / "cards.json",
        [{"Set": "LOF", "Number": "016", "Name": "Qui-Gon Jinn", "Type": "Leader"}],
    )
    service.card_service.search_cards = lambda **_: pytest.fail("requested leader used live search")  # type: ignore[method-assign]

    leaders = service._pick_leaders(
        theme="Force replay",
        format_name="premier",
        leader_names=["Qui-Gon Jinn"],
    )

    assert leaders[0]["lookup_id"] == "LOF/016"


def test_requested_normal_base_uses_local_catalog_without_live_lookup(tmp_path: Path) -> None:
    service = DeckService(CardService())
    service.card_service.catalog = _local_catalog(
        tmp_path / "cards.json",
        [{"Set": "LOF", "Number": "010", "Name": "Echo Base", "Type": "Base"}],
    )
    service.card_service.lookup_card = lambda **_: pytest.fail("requested base used live lookup")  # type: ignore[method-assign]
    service.card_service.search_cards = lambda **_: pytest.fail("requested base used live search")  # type: ignore[method-assign]

    base = service._pick_base(base_name="Echo Base", aspect_pool=set())

    assert base["lookup_id"] == "LOF/010"


def test_missing_requested_normal_cards_fail_without_live_lookup(tmp_path: Path) -> None:
    service = DeckService(CardService())
    service.card_service.catalog = _local_catalog(tmp_path / "cards.json", [])
    service.card_service.lookup_card = lambda **_: pytest.fail("missing requested base used live lookup")  # type: ignore[method-assign]
    service.card_service.search_cards = lambda **_: pytest.fail("missing requested leader used live search")  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="Could not resolve requested leader") as error:
        service._pick_leaders(
            theme="Force replay",
            format_name="premier",
            leader_names=["Missing Leader"],
        )
    assert "as owned cards" not in str(error.value)
    with pytest.raises(ValueError, match="No local base data"):
        service._pick_base(base_name="Missing Base", aspect_pool=set())


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
