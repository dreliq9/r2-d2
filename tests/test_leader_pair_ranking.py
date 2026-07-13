import json
from pathlib import Path

import pytest

from swu_mcp.card_service import CardService
from swu_mcp.catalog import LocalCatalog
from swu_mcp.collection_service import CollectionService
from swu_mcp.deck_service import DeckService


class FakeCardService:
    def __init__(self, leaders: list[dict] | None = None) -> None:
        self.leaders = leaders or []

    def _ensure_local_catalog(self) -> None:
        pass

    def search_cards(self, **kwargs) -> dict:
        return {"cards": self.leaders}


class DummyDeckService(DeckService):
    def __init__(self, leaders: list[dict] | None = None) -> None:
        self.generate_calls = 0
        self.card_service = FakeCardService(leaders)
        self.collection_service = None
        self.sessions = {}

    def _safe_lookup(self, card: dict) -> dict:
        return card

    def generate_deck(self, **kwargs):
        self.generate_calls += 1
        return {
            "analysis": {
                "synergy_score": 50,
                "interaction_density": 10,
                "average_cost": 2.5,
                "deck_size": 80,
                "trait_breakdown": {},
                "role_breakdown": {},
                "available_aspects": [],
            },
            "validation": {"aspect_penalties": {"total_extra_resource_burden": 0}},
            "deck_holoscan": "",
        }


class OwnedLeaderRankingService(DeckService):
    def __init__(self, catalog_path: Path, collection_path: Path) -> None:
        super().__init__(
            CardService(),
            collection_service=CollectionService(collection_path),
        )
        self.card_service.catalog = LocalCatalog(str(catalog_path))
        self.generate_calls = 0

    def generate_deck(self, **kwargs):
        self.generate_calls += 1
        return {
            "analysis": {"synergy_score": 50, "interaction_density": 10, "average_cost": 2.5, "deck_size": 80, "trait_breakdown": {}, "role_breakdown": {}, "available_aspects": []},
            "validation": {"aspect_penalties": {"total_extra_resource_burden": 0}},
            "deck_holoscan": "",
        }


def test_rank_leader_pairs_owned_uses_local_catalog_for_bare_collection_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    collection_path = tmp_path / "collection.json"
    collection_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "set_code": "LOF",
                        "card_number": "016",
                        "count": 1,
                        "foil_count": 0,
                    },
                    {
                        "set_code": "LOF",
                        "card_number": "007",
                        "count": 1,
                        "foil_count": 0,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
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
                    "Aspects": ["Heroism", "Vigilance"],
                },
                {
                    "Set": "LOF",
                    "Number": "007",
                    "Name": "Avar Kriss",
                    "Subtitle": "Marshal of Starlight",
                    "Type": "Leader",
                    "Aspects": ["Heroism", "Vigilance"],
                },
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "swu_mcp.collection_service._read_card_cache", lambda *_: None
    )
    service = OwnedLeaderRankingService(catalog_path, collection_path)

    result = service.rank_leader_pairs(only_owned=True, top_k=1)

    assert result["leader_pool_size"] == 2
    assert result["pairs_considered"] == 1
    assert service.generate_calls == 1
    assert result["ranked"][0]["leaders"] == [
        "Avar Kriss - Marshal of Starlight",
        "Qui-Gon Jinn - Student of the Living Force",
    ]


def test_rank_leader_pairs_shortlist_limits_full_brews() -> None:
    top_k = 2
    leaders = [
        {
            "lookup_id": f"TST/{number:03}",
            "set_code": "TST",
            "number": f"{number:03}",
            "name": f"Leader {number}",
            "subtitle": "Shortlist Test",
            "display_name": f"Leader {number} - Shortlist Test",
            "card_type": "Leader",
            "aspects": ["Villainy"],
        }
        for number in range(1, 7)
    ]
    service = DummyDeckService(leaders)

    result = service.rank_leader_pairs(only_owned=False, top_k=top_k)

    total_pairs = len(leaders) * (len(leaders) - 1) // 2
    assert result["pairs_considered"] == total_pairs
    assert service.generate_calls <= top_k * 3
    assert service.generate_calls < total_pairs


def test_fast_score_prefers_theme_text() -> None:
    service = DummyDeckService()
    first = {"display_name": "Discard Leader", "front_text": "Discard a card from your hand.", "aspects": ["Villainy"]}
    second = {"display_name": "Recursion Leader", "back_text": "Play a card from your discard pile.", "aspects": ["Villainy"]}
    weak = {"display_name": "Blank Leader", "front_text": "", "aspects": ["Villainy"]}

    strong = service._leader_pair_fast_score(first, second, theme="discard recursion", target_packages={"discard_engine"})
    weak_score = service._leader_pair_fast_score(first, weak, theme="discard recursion", target_packages={"discard_engine"})

    assert strong > weak_score
