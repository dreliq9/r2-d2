from pathlib import Path

from swu_mcp.card_identity import CanonicalCardKey, canonical_key
from swu_mcp.collection_service import CollectionService


def test_canonical_key_collapses_same_named_printings() -> None:
    base = {
        "Name": "Qui-Gon Jinn",
        "Subtitle": "Student of the Living Force",
        "Type": "Leader",
    }
    variant = {
        "name": "Qui-Gon Jinn",
        "subtitle": "Student of the Living Force",
        "card_type": "Leader",
        "set_code": "G25",
        "number": "1",
    }

    assert canonical_key(base) == canonical_key(variant)
    assert canonical_key(base) == CanonicalCardKey(
        name="qui-gon jinn",
        subtitle="student of the living force",
        card_type="Leader",
    )


def test_collection_owned_canonical_index_counts_variants(tmp_path: Path) -> None:
    collection_path = tmp_path / "collection.json"
    collection_path.write_text(
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
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    service = CollectionService(collection_path)
    requested = {
        "name": "Qui-Gon Jinn",
        "subtitle": "Student of the Living Force",
        "card_type": "Leader",
        "set_code": "G25",
        "number": "1",
    }

    assert service.owned_canonical_count(requested) == 1
    printing = service.choose_owned_printing(requested)
    assert printing is not None
    assert printing.set_code == "LOF"
    assert printing.card_number == "16"
