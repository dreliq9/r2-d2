from swu_mcp.archetypes import known_archetypes
from swu_mcp.server import swu_known_archetypes


def test_known_archetypes_tool_returns_records() -> None:
    result = swu_known_archetypes()

    assert result["count"] == len(known_archetypes())
    assert any(item["archetype_id"] == "twin-suns-kylo-trench-upgrades" for item in result["archetypes"])
