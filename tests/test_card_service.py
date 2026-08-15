import json

import httpx

from swu_mcp.card_service import CardService
from swu_mcp.catalog import LocalCatalog


def test_wildcard_search_uses_local_catalog_when_api_is_unavailable(tmp_path) -> None:
    catalog_path = tmp_path / "cards.json"
    catalog_path.write_text(
        json.dumps(
            {
                "cards": [
                    {
                        "Set": "SOR",
                        "Number": "001",
                        "Name": "Director Krennic",
                        "Subtitle": "Aspiring to Authority",
                        "Type": "Leader",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    service = CardService()
    service.catalog = LocalCatalog(catalog_path)

    def api_unavailable(*_args, **_kwargs):
        raise httpx.ConnectError("offline")

    service.client.get = api_unavailable

    result = service.search_cards(query="*", limit=1)

    assert result["source"] == "local-fallback"
    assert result["returned_count"] == 1
    assert result["cards"][0]["lookup_id"] == "SOR/001"
