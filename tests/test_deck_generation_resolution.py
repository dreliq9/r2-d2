import json
from collections import Counter
from pathlib import Path

import pytest

from swu_mcp.card_service import CardService
from swu_mcp.card_identity import canonical_key
from swu_mcp.catalog import LocalCatalog
from swu_mcp.collection_service import CollectionService
from swu_mcp.deck_service import DeckCardEntry, DeckService, ParsedDeck, PREMIER, TWIN_SUNS


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


def test_automatic_owned_base_uses_local_catalog_when_cache_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    service.card_service.catalog = _local_catalog(
        tmp_path / "cards.json",
        [{"Set": "LOF", "Number": "010", "Name": "Echo Base", "Type": "Base", "HP": "30"}],
    )
    monkeypatch.setattr("swu_mcp.collection_service._read_card_cache", lambda *_: None)

    base = service._pick_base(base_name=None, aspect_pool=set(), only_owned=True)

    assert base["lookup_id"] == "LOF/010"


def test_automatic_owned_base_resolves_bare_collection_entry_from_local_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
                }
            ],
        ),
    )
    service.card_service.catalog = _local_catalog(
        tmp_path / "cards.json",
        [{"Set": "LOF", "Number": "010", "Name": "Echo Base", "Type": "Base", "HP": "30"}],
    )
    monkeypatch.setattr("swu_mcp.collection_service._read_card_cache", lambda *_: None)

    base = service._pick_base(base_name=None, aspect_pool=set(), only_owned=True)

    assert base["lookup_id"] == "LOF/010"


def test_automatic_owned_leaders_resolve_bare_collection_entries_from_local_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = DeckService(
        CardService(),
        collection_service=_collection(
            tmp_path / "collection.json",
            entries=[
                {"set_code": "LOF", "card_number": "016", "count": 1, "foil_count": 0},
                {"set_code": "LOF", "card_number": "007", "count": 1, "foil_count": 0},
            ],
        ),
    )
    service.card_service.catalog = _local_catalog(
        tmp_path / "cards.json",
        [
            {"Set": "LOF", "Number": "016", "Name": "Qui-Gon Jinn", "Type": "Leader", "Aspects": ["Vigilance"]},
            {"Set": "LOF", "Number": "007", "Name": "Avar Kriss", "Type": "Leader", "Aspects": ["Vigilance"]},
        ],
    )
    monkeypatch.setattr("swu_mcp.collection_service._read_card_cache", lambda *_: None)

    leaders = service._pick_leaders(
        theme="Force replay", format_name=TWIN_SUNS, leader_names=None, only_owned=True
    )

    assert {leader["lookup_id"] for leader in leaders} == {"LOF/016", "LOF/007"}


def test_bare_owned_main_card_resolves_and_counts_from_local_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = DeckService(
        CardService(),
        collection_service=_collection(
            tmp_path / "collection.json",
            entries=[{"set_code": "LOF", "card_number": "020", "count": 2, "foil_count": 0}],
        ),
    )
    candidate = {
        "name": "Rebel Pathfinder",
        "display_name": "Rebel Pathfinder",
        "card_type": "Unit",
        "set_code": "SOR",
        "number": "001",
        "lookup_id": "SOR/001",
    }
    service.card_service.catalog = _local_catalog(
        tmp_path / "cards.json",
        [
            {"Set": "SOR", "Number": "001", "Name": "Rebel Pathfinder", "Type": "Unit"},
            {"Set": "LOF", "Number": "020", "Name": "Rebel Pathfinder", "Type": "Unit"},
        ],
    )
    monkeypatch.setattr("swu_mcp.collection_service._read_card_cache", lambda *_: None)

    resolved = service._resolve_owned_printing(candidate)

    assert resolved is not None
    assert resolved["lookup_id"] == "LOF/020"
    assert service._candidate_owned_count(candidate) == 2
    assert service._candidate_is_owned(candidate, minimum=2)


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


def test_automatic_twin_suns_leaders_are_canonically_distinct(tmp_path: Path) -> None:
    service = DeckService(CardService())
    service.card_service.catalog = _local_catalog(
        tmp_path / "cards.json",
        [
            {"Set": "LOF", "Number": "016", "Name": "Qui-Gon Jinn", "Type": "Leader", "Aspects": ["Vigilance"]},
            {"Set": "SOR", "Number": "001", "Name": "Qui-Gon Jinn", "Type": "Leader", "Aspects": ["Vigilance"]},
            {"Set": "LOF", "Number": "007", "Name": "Avar Kriss", "Type": "Leader", "Aspects": ["Vigilance"]},
        ],
    )

    leaders = service._pick_leaders(theme="Force replay", format_name=TWIN_SUNS, leader_names=None)

    assert len({canonical_key(leader) for leader in leaders}) == 2


def test_candidate_discovery_fails_locally_without_live_search(tmp_path: Path) -> None:
    service = DeckService(CardService())
    service.card_service.catalog = _local_catalog(tmp_path / "cards.json", [])
    service.card_service.search_cards = lambda **_: pytest.fail("candidate discovery used live search")  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="No local candidate data"):
        service._candidate_cards(goal_query="Force replay", available_aspects=set(), local_only=True)


def test_owned_candidate_discovery_reuses_supplied_printing_cache(tmp_path: Path) -> None:
    service = DeckService(
        CardService(),
        collection_service=_collection(tmp_path / "collection.json", entries=[]),
    )
    catalog_card = {
        "Set": "SOR",
        "Number": "020",
        "Name": "Cached Unit",
        "Type": "Unit",
        "Aspects": ["Command"],
        "Cost": "2",
        "Power": "2",
        "HP": "2",
    }
    owned_card = {
        "lookup_id": "LOF/020",
        "set_code": "LOF",
        "number": "020",
        "name": "Cached Unit",
        "display_name": "Cached Unit",
        "card_type": "Unit",
        "aspects": ["Command"],
        "traits": [],
        "keywords": [],
        "front_text": "",
        "cost": "2",
        "power": "2",
        "hp": "2",
    }
    service.card_service.catalog = _local_catalog(tmp_path / "cards.json", [catalog_card])
    service._owned_printings_by_canonical_key = lambda: pytest.fail("candidate discovery rebuilt owned printings")  # type: ignore[method-assign]

    candidates = service._candidate_cards(
        goal_query="cached",
        available_aspects={"Command"},
        only_owned=True,
        local_only=True,
        owned_printings={canonical_key(owned_card): owned_card},
    )

    assert len(candidates) == 1
    assert candidates[0]["lookup_id"] == "LOF/020"
    assert candidates[0]["set_code"] == "LOF"
    assert candidates[0]["number"] == "020"


def test_suggestion_candidate_discovery_keeps_search_fallback() -> None:
    service = DeckService(CardService())
    service.card_service.catalog = LocalCatalog(None)
    service.card_service._ensure_local_catalog = lambda: None  # type: ignore[method-assign]
    fallback_card = {
        "lookup_id": "LOF/020",
        "set_code": "LOF",
        "number": "020",
        "name": "Rebel Pathfinder",
        "display_name": "Rebel Pathfinder",
        "card_type": "Unit",
        "aspects": [],
        "traits": [],
        "keywords": [],
        "front_text": "",
    }
    service.card_service.search_cards = lambda **_: {"cards": [fallback_card]}  # type: ignore[method-assign]

    candidates = service._candidate_cards(goal_query="rebel", available_aspects=set())

    assert candidates == [fallback_card]


def test_generation_analyzes_resolved_deck_without_lookup_card() -> None:
    service = DeckService(CardService())
    leader = {
        "lookup_id": "LOF/001",
        "set_code": "LOF",
        "number": "001",
        "name": "Qui-Gon Jinn",
        "display_name": "Qui-Gon Jinn",
        "card_type": "Leader",
        "aspects": ["Vigilance"],
        "traits": [],
        "keywords": [],
        "front_text": "",
    }
    base = {
        "lookup_id": "LOF/002",
        "set_code": "LOF",
        "number": "002",
        "name": "Echo Base",
        "display_name": "Echo Base",
        "card_type": "Base",
        "aspects": ["Vigilance"],
        "traits": [],
        "keywords": [],
        "front_text": "",
        "hp": "30",
    }
    candidates = [
        {
            "lookup_id": f"LOF/{index:03d}",
            "set_code": "LOF",
            "number": f"{index:03d}",
            "name": f"Unit {index}",
            "display_name": f"Unit {index}",
            "card_type": "Unit",
            "aspects": ["Vigilance"],
            "traits": [],
            "keywords": [],
            "front_text": "",
            "cost": "2",
            "power": "2",
            "hp": "2",
        }
        for index in range(10, 31)
    ]
    service._pick_leaders = lambda **_: [leader]  # type: ignore[method-assign]
    service._pick_base = lambda **_: base  # type: ignore[method-assign]
    service._candidate_cards = lambda **_: candidates  # type: ignore[method-assign]
    service.card_service.lookup_card = lambda **_: pytest.fail("post-generation analysis used live lookup")  # type: ignore[method-assign]

    generated = service.generate_deck(theme="Vigilance units")

    assert generated["analysis"]["deck_size"] >= 50


def test_only_owned_generation_uses_cached_counts_for_quantity_caps(tmp_path: Path) -> None:
    service = DeckService(
        CardService(),
        collection_service=_collection(tmp_path / "collection.json", entries=[]),
    )
    leader = {
        "lookup_id": "TST/001",
        "set_code": "TST",
        "number": "001",
        "name": "Command Leader",
        "display_name": "Command Leader",
        "card_type": "Leader",
        "aspects": ["Command"],
        "traits": [],
        "keywords": [],
        "front_text": "",
    }
    base = {
        "lookup_id": "TST/002",
        "set_code": "TST",
        "number": "002",
        "name": "Command Base",
        "display_name": "Command Base",
        "card_type": "Base",
        "aspects": ["Command"],
        "traits": [],
        "keywords": [],
        "front_text": "",
    }

    owned_main = {
        "lookup_id": "TST/040",
        "set_code": "TST",
        "number": "040",
        "name": "Mixed Source Unit",
        "display_name": "Mixed Source Unit",
        "card_type": "Unit",
        "aspects": ["Command"],
        "traits": [],
        "keywords": [],
        "front_text": "Draw a card. Deal 2 damage to a unit.",
        "cost": "2",
        "power": "5",
        "hp": "5",
    }
    filler_cards = [
        {
            "lookup_id": f"TST/{100 + index:03d}",
            "set_code": "TST",
            "number": f"{100 + index:03d}",
            "name": f"Filler Unit {index}",
            "display_name": f"Filler Unit {index}",
            "card_type": "Unit",
            "aspects": ["Command"],
            "traits": [],
            "keywords": [],
            "front_text": "",
            "cost": "2",
            "power": "1",
            "hp": "1",
        }
        for index in range(47)
    ]
    all_cards = [owned_main, *filler_cards]
    service.card_service.catalog = _local_catalog(
        tmp_path / "cards.json",
        [
            {
                "Set": card["set_code"],
                "Number": card["number"],
                "Name": card["name"],
                "Type": card["card_type"],
                "Aspects": card["aspects"],
                "Traits": card["traits"],
                "Keywords": card["keywords"],
                "FrontText": card["front_text"],
                "Cost": card["cost"],
                "Power": card["power"],
                "HP": card["hp"],
            }
            for card in all_cards
        ],
    )
    service._pick_leaders = lambda **_: [leader]  # type: ignore[method-assign]
    service._pick_base = lambda **_: base  # type: ignore[method-assign]
    count_calls = 0

    def owned_counts() -> Counter:
        nonlocal count_calls
        count_calls += 1
        counts = Counter({canonical_key(card): 1 for card in filler_cards})
        counts[canonical_key(owned_main)] = 3
        return counts

    service._owned_counts_by_canonical_key = owned_counts  # type: ignore[method-assign]
    service._owned_printings_by_canonical_key = lambda: {canonical_key(card): card for card in all_cards}  # type: ignore[method-assign]

    generated = service.generate_deck(
        theme="command units",
        format_name=PREMIER,
        only_owned=True,
    )

    assert "\n3 Mixed Source Unit\n" in f"\n{generated['deck']}\n"
    assert count_calls == 1


def test_twin_suns_validation_rejects_duplicate_canonical_leaders() -> None:
    duplicate = {
        "name": "Qui-Gon Jinn",
        "display_name": "Qui-Gon Jinn",
        "card_type": "Leader",
        "set_code": "LOF",
        "number": "016",
    }
    parsed = ParsedDeck(
        format_name=TWIN_SUNS,
        leaders=[
            DeckCardEntry(quantity=1, name="Qui-Gon Jinn", zone="leaders", card=duplicate),
            DeckCardEntry(quantity=1, name="Qui-Gon Jinn", zone="leaders", card={**duplicate, "set_code": "SOR", "number": "001"}),
        ],
    )

    validation = DeckService(CardService()).validate_parsed_deck(parsed)

    assert "Twin Suns requires two distinct canonical leaders." in validation["errors"]


def test_twin_suns_validation_rejects_duplicate_canonical_main_deck_cards_with_rendered_name_variants() -> None:
    leaders = [
        DeckCardEntry(
            quantity=1,
            name="Hero Leader",
            zone="leaders",
            card={
                "name": "Hero Leader",
                "display_name": "Hero Leader",
                "card_type": "Leader",
                "set_code": "TST",
                "number": "001",
                "lookup_id": "TST/001",
                "aspects": ["Heroism", "Vigilance"],
            },
        ),
        DeckCardEntry(
            quantity=1,
            name="Hero Partner",
            zone="leaders",
            card={
                "name": "Hero Partner",
                "display_name": "Hero Partner",
                "card_type": "Leader",
                "set_code": "TST",
                "number": "002",
                "lookup_id": "TST/002",
                "aspects": ["Heroism", "Command"],
            },
        ),
    ]
    base = DeckCardEntry(
        quantity=1,
        name="Hero Base",
        zone="bases",
        card={
            "name": "Hero Base",
            "display_name": "Hero Base",
            "card_type": "Base",
            "set_code": "TST",
            "number": "003",
            "lookup_id": "TST/003",
            "aspects": ["Heroism"],
        },
    )
    duplicate_cards = [
        {
            "name": "Prepare For Takeoff",
            "display_name": "Prepare For Takeoff",
            "card_type": "Event",
            "set_code": "TST",
            "number": "010",
            "lookup_id": "TST/010",
            "aspects": ["Heroism"],
            "front_text": "",
        },
        {
            "name": "Prepare for Takeoff",
            "display_name": "Prepare for Takeoff",
            "card_type": "Event",
            "set_code": "TST",
            "number": "011",
            "lookup_id": "TST/011",
            "aspects": ["Heroism"],
            "front_text": "",
        },
    ]
    main_deck = [
        DeckCardEntry(
            quantity=1,
            name=str(card["display_name"]),
            zone="main_deck",
            card=card,
        )
        for card in duplicate_cards
    ] + [
        DeckCardEntry(
            quantity=1,
            name=f"Unique Unit {index}",
            zone="main_deck",
            card={
                "name": f"Unique Unit {index}",
                "display_name": f"Unique Unit {index}",
                "card_type": "Unit",
                "set_code": "TST",
                "number": f"{100 + index}",
                "lookup_id": f"TST/{100 + index}",
                "aspects": ["Heroism"],
                "cost": "2",
                "power": "2",
                "hp": "2",
            },
        )
        for index in range(78)
    ]
    parsed = ParsedDeck(
        format_name=TWIN_SUNS,
        leaders=leaders,
        bases=[base],
        main_deck=main_deck,
    )

    validation = DeckService(CardService()).validate_parsed_deck(parsed)

    assert not validation["legal"]
    assert "Prepare For Takeoff appears 2 times; the format limit is 1." in validation["errors"]
