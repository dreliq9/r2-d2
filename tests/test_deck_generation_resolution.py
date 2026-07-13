from pathlib import Path

import pytest

from swu_mcp.card_service import CardService
from swu_mcp.collection_service import CollectionService
from swu_mcp.deck_service import DeckService, TWIN_SUNS


def _collection(path: Path) -> CollectionService:
    path.write_text(
        """
        {
          "entries": [
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
          ]
        }
        """,
        encoding="utf-8",
    )
    return CollectionService(path)


def test_requested_twin_suns_leaders_resolve_by_owned_canonical_identity(tmp_path: Path) -> None:
    service = DeckService(CardService(), collection_service=_collection(tmp_path / "collection.json"))

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
