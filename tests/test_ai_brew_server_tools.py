import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from swu_mcp import server
from swu_mcp.ai_brew_service import AIBrewService
from swu_mcp.ai_brew_session import BrewSessionStore
from swu_mcp.card_service import CardService
from swu_mcp.catalog import LocalCatalog
from swu_mcp.collection_service import CollectionService
from swu_mcp.deck_service import DeckService
from swu_mcp.types import (
    BrewCardChange,
    BrewContextFilters,
    BrewObjectiveDirections,
    BrewPackage,
    BrewProbabilityCategory,
    BrewRoleTargets,
    BrewSwapSuggestion,
)


class EchoAIBrewService:
    def _reply(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"status": "ok", "method": method, "payload": payload}

    def start_brew(self, **kwargs: Any) -> dict[str, Any]:
        return self._reply("start_brew", kwargs)

    def get_context(self, **kwargs: Any) -> dict[str, Any]:
        return self._reply("get_context", kwargs)

    def record_decisions(self, **kwargs: Any) -> dict[str, Any]:
        return self._reply("record_decisions", kwargs)

    def evaluate_brew(self, **kwargs: Any) -> dict[str, Any]:
        return self._reply("evaluate_brew", kwargs)

    def finalize_brew(self, **kwargs: Any) -> dict[str, Any]:
        return self._reply("finalize_brew", kwargs)


class NoAutomaticDeckService(DeckService):
    """Real deck service that makes an accidental automatic brew call fail."""

    def __init__(self, card_service: CardService, collection_service: CollectionService) -> None:
        super().__init__(card_service, collection_service=collection_service)
        self.automatic_calls: list[str] = []

    def _unexpected_automatic_call(self, name: str) -> None:
        self.automatic_calls.append(name)
        pytest.fail(f"AI-brew wrapper workflow must not call DeckService.{name}.")

    def generate_deck(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._unexpected_automatic_call("generate_deck")
        return {}

    def optimize_deck(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._unexpected_automatic_call("optimize_deck")
        return {}

    def suggest_cards(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._unexpected_automatic_call("suggest_cards")
        return {}


def _tools() -> dict[str, Any]:
    return {tool.name: tool for tool in asyncio.run(server.mcp.list_tools())}


NEW_TOOL_SCHEMA_HASHES = {
    "swu_start_ai_brew": "0e71efa4a84efd4d2df36d51a6bc5fdcaf9c684f1e06e8fc8c564be25799883a",
    "swu_get_brew_context": "0d3749bcb1c0481023e24da8bb11791d23d85187d13de74de813eeae1ba0c437",
    "swu_record_brew_decisions": "a89ed4620495ef23deeb10b2e70e1d585ed4cf769c2986184dec293a365891e8",
    "swu_evaluate_ai_brew": "c8eb2d3c780372cfb37df0173607c03028f3ad83297d8a4332fd479528d2684f",
    "swu_finalize_ai_brew": "7f5605656fa6b95e1e11901ebca724af4c73cfdfe2fbdda4732a7beee4281b5c",
}


def _schema_variant(schema: dict[str, Any], schema_type: str) -> dict[str, Any]:
    return next(item for item in schema["anyOf"] if item.get("type") == schema_type)


def _object_schema(schema: dict[str, Any]) -> dict[str, Any]:
    return _schema_variant(schema, "object")


def _array_schema(schema: dict[str, Any]) -> dict[str, Any]:
    return _schema_variant(schema, "array")


def _schema_hash(schema: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _contains_object_schema(schema: object, expected_fields: set[str]) -> bool:
    if isinstance(schema, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict) and expected_fields.issubset(properties):
            return True
        return any(_contains_object_schema(value, expected_fields) for value in schema.values())
    if isinstance(schema, list):
        return any(_contains_object_schema(value, expected_fields) for value in schema)
    return False


def test_ai_brew_tools_are_registered_with_explicit_nested_schemas() -> None:
    tools = _tools()

    approved_names = {
        "swu_start_ai_brew",
        "swu_get_brew_context",
        "swu_record_brew_decisions",
        "swu_evaluate_ai_brew",
        "swu_finalize_ai_brew",
    }
    assert approved_names == set(NEW_TOOL_SCHEMA_HASHES)
    assert approved_names <= set(tools)
    start_schema = tools["swu_start_ai_brew"].parameters
    context_schema = tools["swu_get_brew_context"].parameters
    record_schema = tools["swu_record_brew_decisions"].parameters
    evaluate_schema = tools["swu_evaluate_ai_brew"].parameters
    finalize_schema = tools["swu_finalize_ai_brew"].parameters
    start = start_schema["properties"]
    context = context_schema["properties"]
    record = record_schema["properties"]
    evaluate = evaluate_schema["properties"]
    finalize = finalize_schema["properties"]
    filter_schema = _object_schema(context["filters"])
    filters = filter_schema["properties"]
    card_change_schema = _array_schema(record["additions"])["items"]
    card_change = card_change_schema["properties"]
    package_schema = _array_schema(record["packages"])["items"]
    package = package_schema["properties"]
    role_target_schema = _object_schema(record["role_targets"])
    probability_schema = _array_schema(evaluate["probability_categories"])["items"]
    probability = probability_schema["properties"]
    swap_schema = _array_schema(evaluate["candidate_swaps"])["items"]
    swap = swap_schema["properties"]
    objective_schema = _object_schema(evaluate["objective_directions"])
    objective_directions = objective_schema["properties"]

    assert start_schema["required"] == ["format_name", "leader_names", "base_name", "theme"]
    assert start["format_name"]["enum"] == ["premier", "twin_suns"]
    assert start["leader_names"]["minItems"] == 1
    assert start["base_name"]["minLength"] == 1
    assert start["theme"]["minLength"] == 1
    assert {field: start[field]["default"] for field in ("only_owned", "allow_off_aspect")} == {
        "only_owned": False,
        "allow_off_aspect": False,
    }
    assert start["target_matchups"]["default"] is None
    assert start["meta_context"]["default"] is None
    assert start["session_id"]["default"] is None

    assert context_schema["required"] == ["session_id", "intent"]
    assert context["session_id"]["minLength"] == 1
    assert context["intent"]["enum"] == [
        "candidates", "card-candidates", "session-summary", "revision-history"
    ]
    assert context["limit"]["minimum"] == 1
    assert context["limit"]["maximum"] == 100
    assert context["limit"]["default"] == 25
    assert context["filters"]["default"] is None
    assert context["cursor"]["default"] is None
    assert set(filters) == {
        "roles", "packages", "min_cost", "max_cost", "card_types", "aspects", "traits",
        "keywords", "text", "minimum_owned", "inclusion_state", "type", "aspect", "trait", "query",
    }
    assert filter_schema["additionalProperties"] is False
    assert BrewContextFilters().model_dump(mode="json") == {
        "roles": [],
        "packages": [],
        "min_cost": None,
        "max_cost": None,
        "card_types": [],
        "aspects": [],
        "traits": [],
        "keywords": [],
        "text": None,
        "minimum_owned": None,
        "inclusion_state": "any",
        "type": None,
        "aspect": None,
        "trait": None,
        "query": None,
    }
    for field in ("roles", "packages", "card_types", "aspects", "traits", "keywords"):
        assert filters[field] == {"type": "array", "items": {"type": "string"}}
    for field in ("min_cost", "max_cost", "minimum_owned"):
        assert _schema_variant(filters[field], "integer")["minimum"] == 0
    assert filters["text"]["default"] is None
    assert filters["inclusion_state"]["default"] == "any"
    assert filters["inclusion_state"]["enum"] == ["included", "excluded", "any"]

    assert record_schema["required"] == ["session_id", "expected_revision"]
    assert record["session_id"]["minLength"] == 1
    assert set(card_change) == {"card_id", "quantity", "zone"}
    assert card_change_schema["required"] == ["card_id", "quantity"]
    assert card_change_schema["additionalProperties"] is False
    assert card_change["quantity"]["minimum"] == 1
    assert card_change["zone"]["default"] == "main_deck"
    assert card_change["zone"]["enum"] == ["main_deck", "sideboard"]
    for field in ("cuts", "reservations", "rejected_cards"):
        assert _array_schema(record[field])["items"] == card_change_schema
    assert package_schema["required"] == ["name", "target"]
    assert package_schema["additionalProperties"] is False
    assert package["name"]["minLength"] == 1
    assert package["target"]["minimum"] == 0
    assert role_target_schema == {
        "type": "object",
        "additionalProperties": {"type": "integer", "minimum": 0},
    }
    assert record["thesis"]["default"] is None
    assert record["packages"]["default"] is None
    assert record["role_targets"]["default"] is None
    for field in ("additions", "cuts", "reservations", "rejected_cards", "evidence_ids"):
        assert record[field]["default"] is None
    assert record["rationale"]["default"] == ""
    assert record["advisory_report_id"]["default"] is None
    assert record["accept_stale_evidence"]["default"] is False
    assert record["expected_revision"]["minimum"] == 0
    assert _schema_variant(record["restore_revision"], "integer")["minimum"] == 0
    assert record["restore_revision"]["default"] is None
    assert record["refresh_collection"]["default"] is False

    assert evaluate_schema["required"] == ["session_id"]
    assert evaluate["session_id"]["minLength"] == 1
    assert probability_schema["required"] == ["name", "printing_ids"]
    assert probability_schema["additionalProperties"] is False
    assert probability["name"]["minLength"] == 1
    assert probability["printing_ids"]["minItems"] == 1
    assert probability["printing_ids"]["maxItems"] == 80
    assert probability["printing_ids"]["items"] == {"type": "string"}
    assert probability["kind"]["default"] is None
    assert probability["kind"]["anyOf"][0]["enum"] == ["enabler", "payoff"]
    assert swap_schema["required"] == ["suggestion_id"]
    assert swap_schema["additionalProperties"] is False
    assert set(swap) == {"suggestion_id", "adds", "cuts"}
    assert swap["suggestion_id"]["minLength"] == 1
    assert swap["adds"] == {
        "type": "array",
        "items": card_change_schema,
        "maxItems": 80,
    }
    assert swap["cuts"] == {
        "type": "array",
        "items": card_change_schema,
        "maxItems": 80,
    }
    assert objective_schema["additionalProperties"] is False
    assert set(objective_directions) == {
        "legality", "plan_reliability", "curve_quality", "interaction", "card_advantage",
        "resilience", "synergy", "matchup_fit",
    }
    for direction in objective_directions.values():
        assert direction["anyOf"][0]["enum"] == ["min", "max"]
        assert direction["default"] is None
    assert _schema_variant(evaluate["revision"], "integer")["minimum"] == 0
    assert evaluate["revision"]["default"] is None
    turn_horizons = _array_schema(evaluate["turn_horizons"])
    assert turn_horizons["items"]["minimum"] == 0
    assert turn_horizons["items"]["maximum"] == 80
    assert turn_horizons["maxItems"] == 20
    assert evaluate["turn_horizons"]["default"] is None
    assert evaluate["mulligan_redraws"]["minimum"] == 0
    assert evaluate["mulligan_redraws"]["maximum"] == 10
    assert evaluate["mulligan_redraws"]["default"] == 1
    assert evaluate["simulation_seed"]["default"] == 1
    assert evaluate["simulation_count"]["minimum"] == 1
    assert evaluate["simulation_count"]["maximum"] == 10_000
    assert evaluate["simulation_count"]["default"] == 1000
    assert _array_schema(evaluate["probability_categories"])["maxItems"] == 32
    assert _array_schema(evaluate["candidate_swaps"])["maxItems"] == 20
    for field in ("matchup_inputs", "probability_categories", "candidate_swaps", "objective_directions"):
        assert evaluate[field]["default"] is None

    assert finalize_schema["required"] == ["session_id", "expected_revision"]
    assert finalize["session_id"]["minLength"] == 1
    assert finalize["expected_revision"]["minimum"] == 0
    assert "caller AI makes card choices" in tools["swu_start_ai_brew"].description
    assert "caller AI makes card choices" in tools["swu_get_brew_context"].description
    assert "caller AI makes card choices" in tools["swu_record_brew_decisions"].description
    assert "advisory" in tools["swu_evaluate_ai_brew"].description
    assert "never applied automatically" in tools["swu_evaluate_ai_brew"].description
    assert "legal and current" in tools["swu_finalize_ai_brew"].description


def test_ai_brew_tool_full_schemas_match_canonical_hashes() -> None:
    tools = _tools()

    assert {
        name: _schema_hash(tools[name].parameters)
        for name in NEW_TOOL_SCHEMA_HASHES
    } == NEW_TOOL_SCHEMA_HASHES


def test_ai_brew_wrappers_delegate_typed_inputs_as_json_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "ai_brew_service", EchoAIBrewService())
    filters = BrewContextFilters(
        roles=["control"],
        packages=["force_engine"],
        min_cost=1,
        max_cost=5,
        card_types=["Unit"],
        aspects=["Heroism"],
        traits=["Jedi"],
        keywords=["Restore"],
        text="Force",
        minimum_owned=1,
        inclusion_state="included",
    )
    change = BrewCardChange(card_id="SOR/004", quantity=2)
    category = BrewProbabilityCategory(
        name="enabler",
        printing_ids=["SOR/004"],
        kind="enabler",
    )
    swap = BrewSwapSuggestion(
        suggestion_id="test-swap",
        adds=[change],
        cuts=[BrewCardChange(card_id="SOR/005", quantity=1)],
    )

    started = server.swu_start_ai_brew(
        format_name="premier",
        leader_names=["Leader One"],
        base_name="Base One",
        theme="Force control",
        target_matchups=["aggro"],
        meta_context={"source": "test"},
    )
    context = server.swu_get_brew_context(
        session_id="session-1",
        intent="candidates",
        filters=filters,
    )
    decision = server.swu_record_brew_decisions(
        session_id="session-1",
        expected_revision=2,
        thesis="Protect the Force plan.",
        packages=[BrewPackage(name="force_engine", target=8)],
        role_targets=BrewRoleTargets(root={"defense": 7}),
        additions=[change],
        cuts=[BrewCardChange(card_id="SOR/005", quantity=1)],
        reservations=[BrewCardChange(card_id="SOR/006", quantity=1, zone="sideboard")],
        rejected_cards=[BrewCardChange(card_id="SOR/007", quantity=1)],
        rationale="The caller selected these cards.",
        evidence_ids=["evidence-1"],
        advisory_report_id="report-1",
        accept_stale_evidence=True,
        restore_revision=1,
        refresh_collection=True,
    )
    evaluation = server.swu_evaluate_ai_brew(
        session_id="session-1",
        revision=2,
        turn_horizons=[1, 3],
        mulligan_redraws=1,
        simulation_seed=17,
        simulation_count=31,
        matchup_inputs={"speed": "fast"},
        probability_categories=[category],
        candidate_swaps=[swap],
        objective_directions=BrewObjectiveDirections(
            curve_quality="max",
            plan_reliability="max",
        ),
    )
    finalized = server.swu_finalize_ai_brew(session_id="session-1", expected_revision=2)

    assert all(result["status"] == "ok" for result in [started, context, decision, evaluation, finalized])
    assert context["payload"]["filters"] == filters.model_dump(mode="json")
    assert decision["payload"]["additions"] == [
        {"printing_id": "SOR/004", "quantity": 2, "zone": "main_deck"}
    ]
    assert decision["payload"]["role_targets"] == {"defense": 7}
    assert decision["payload"]["accept_stale_evidence"] is True
    assert evaluation["payload"]["probability_categories"] == [
        {"name": "enabler", "printing_ids": ["SOR/004"], "kind": "enabler"}
    ]
    assert evaluation["payload"]["candidate_swaps"] == [
        {
            "suggestion_id": "test-swap",
            "adds": [{"printing_id": "SOR/004", "quantity": 2, "zone": "main_deck"}],
            "cuts": [{"printing_id": "SOR/005", "quantity": 1, "zone": "main_deck"}],
        }
    ]
    assert evaluation["payload"]["objective_directions"] == {
        "curve_quality": "max",
        "plan_reliability": "max",
    }


def _workflow_card(
    number: int,
    name: str,
    card_type: str,
    *,
    subtitle: str | None = None,
    aspects: list[str] | None = None,
    cost: str | None = None,
) -> dict[str, object]:
    return {
        "Set": "FIN",
        "Number": f"{number:03d}",
        "Name": name,
        "Subtitle": subtitle,
        "Type": card_type,
        "Aspects": aspects or [],
        "Traits": ["JEDI"] if card_type == "Unit" else [],
        "FrontText": "When Played: Draw a card." if card_type == "Unit" else "",
        "Keywords": ["Sentinel"] if card_type == "Unit" and number % 5 == 0 else [],
        "Cost": cost,
        "Arenas": ["Ground"] if card_type == "Unit" else [],
    }


def _real_workflow_service(tmp_path: Path) -> tuple[AIBrewService, NoAutomaticDeckService]:
    cards = [
        _workflow_card(
            1,
            "Workflow Leader",
            "Leader",
            subtitle="Mentor",
            aspects=["Vigilance", "Heroism"],
        ),
        _workflow_card(2, "Workflow Base", "Base", aspects=["Vigilance"]),
        *[
            _workflow_card(
                number,
                f"Workflow Unit {number:03d}",
                "Unit",
                aspects=["Vigilance", "Heroism"],
                cost=str(1 + number % 4),
            )
            for number in range(4, 21)
        ],
    ]
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(cards), encoding="utf-8")
    collection_path = tmp_path / "collection.json"
    collection_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "set_code": "FIN",
                        "card_number": f"{number:03d}",
                        "count": 3 if number >= 4 else 1,
                        "foil_count": 0,
                    }
                    for number in [1, 2, *range(4, 21)]
                ]
            }
        ),
        encoding="utf-8",
    )
    card_service = CardService()
    card_service.catalog = LocalCatalog(str(catalog_path))
    card_service.cache_dir = tmp_path / "cache"
    card_service.cache_dir.mkdir()
    collection_service = CollectionService(collection_path)
    deck_service = NoAutomaticDeckService(card_service, collection_service)
    return (
        AIBrewService(
            card_service,
            collection_service,
            deck_service,
            BrewSessionStore(tmp_path / "brews"),
        ),
        deck_service,
    )


def test_all_ai_brew_wrappers_complete_real_premier_workflow_without_auto_brewing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, deck_service = _real_workflow_service(tmp_path)
    monkeypatch.setattr(server, "ai_brew_service", service)

    started = server.swu_start_ai_brew(
        format_name="premier",
        leader_names=["Workflow Leader - Mentor"],
        base_name="Workflow Base",
        theme="Jedi midrange",
        only_owned=True,
        target_matchups=["aggro"],
        meta_context={"workflow": "task-7"},
    )
    context = server.swu_get_brew_context(
        session_id=started["session_id"],
        intent="candidates",
        filters=BrewContextFilters(card_types=["Unit"], min_cost=1),
        limit=100,
    )
    intended_quantities = {
        **{f"FIN/{number:03d}": 3 for number in range(4, 20)},
        "FIN/020": 2,
    }
    context_cards_by_id = {
        str(card["printing_id"]): card
        for card in context["cards"]
    }
    selected_card_ids = [
        printing_id
        for printing_id in context_cards_by_id
        if printing_id in intended_quantities
    ]
    assert set(selected_card_ids) == set(intended_quantities)
    assert all(
        context_cards_by_id[printing_id]["card"]["lookup_id"] == printing_id
        for printing_id in selected_card_ids
    )
    additions = [
        BrewCardChange(card_id=printing_id, quantity=intended_quantities[printing_id])
        for printing_id in selected_card_ids
    ]
    assert sum(addition.quantity for addition in additions) == 50
    decisions = server.swu_record_brew_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        thesis="Use resilient Jedi units to build a legal Premier deck.",
        additions=additions,
        rationale="The caller AI explicitly selected the complete 50-card main deck.",
    )
    evaluation = server.swu_evaluate_ai_brew(
        session_id=started["session_id"],
        revision=decisions["revision"],
        turn_horizons=[1, 3],
        simulation_seed=17,
        simulation_count=7,
        probability_categories=[
            BrewProbabilityCategory(
                name="enabler",
                printing_ids=["FIN/004", "FIN/005"],
                kind="enabler",
            ),
            BrewProbabilityCategory(
                name="payoff",
                printing_ids=["FIN/005", "FIN/006"],
                kind="payoff",
            ),
        ],
    )
    finalized = server.swu_finalize_ai_brew(
        session_id=started["session_id"],
        expected_revision=decisions["revision"],
    )

    assert all(result["status"] == "ok" for result in (started, context, decisions, evaluation, finalized))
    for result in (started, context, decisions, evaluation, finalized):
        assert set(("session_id", "revision", "stage", "diagnostics", "next_steps")) <= set(result)
        assert isinstance(result["diagnostics"], list)
        assert isinstance(result["next_steps"], list)
    assert started["revision"] == 0
    assert context["total_candidates"] == 17
    assert decisions["revision"] == 1
    assert evaluation["revision"] == decisions["revision"]
    assert [
        (category["name"], category["successes"])
        for category in evaluation["probabilities"]["categories"]
    ] == [("enabler", 6), ("payoff", 6)]
    assert len(evaluation["probabilities"]["enabler_payoff"]) == 1
    pair = evaluation["probabilities"]["enabler_payoff"][0]
    assert {
        key: pair[key]
        for key in ("enabler", "payoff", "population", "enablers", "payoffs", "overlap")
    } == {
        "enabler": "enabler",
        "payoff": "payoff",
        "population": 50,
        "enablers": 6,
        "payoffs": 6,
        "overlap": 3,
    }
    assert set(pair["by_turn"]) == {"1", "3"}
    assert all(0 <= turn["result"] <= 1 for turn in pair["by_turn"].values())
    assert 0 <= pair["overlap"] <= min(pair["enablers"], pair["payoffs"])
    assert finalized["revision"] == decisions["revision"]
    assert finalized["stage"] == "finalized"
    assert finalized["validation"]["legal"] is True
    assert finalized["validation"]["counts"] == {
        "leaders": 1,
        "bases": 1,
        "main_deck": 50,
        "sideboard": 0,
    }
    assert finalized["receipt"]["revision"] == decisions["revision"]
    assert finalized["receipt"]["current_advisory_report"] == evaluation["report_id"]
    assert finalized["receipt"]["decision_history"] == finalized["decision_history"]
    assert finalized["decision_history"][0]["resulting_revision"] == decisions["revision"]
    assert finalized["plain_text"]["export_format"] == "plain_text"
    assert finalized["plain_text"]["deck"]
    assert finalized["holoscan"]["export_format"] == "holoscan"
    assert finalized["holoscan"]["deck"]
    assert service.store.load(started["session_id"]).finalization_receipts == [finalized["receipt"]]
    assert deck_service.automatic_calls == []


def test_ai_brew_wrappers_return_structured_service_failures() -> None:
    missing_session = "task-7-missing-session"
    results = [
        server.swu_start_ai_brew(
            format_name="not-a-format",
            leader_names=[],
            base_name="",
            theme="",
        ),
        server.swu_get_brew_context(session_id=missing_session, intent="session-summary"),
        server.swu_record_brew_decisions(
            session_id=missing_session,
            expected_revision=0,
            rationale="A missing session must not raise.",
        ),
        server.swu_evaluate_ai_brew(session_id=missing_session),
        server.swu_finalize_ai_brew(session_id=missing_session, expected_revision=0),
    ]

    for result in results:
        assert result["status"] == "fail"
        assert set(("session_id", "revision", "stage", "diagnostics", "next_steps")) <= set(result)
        assert result["diagnostics"]
        assert result["next_steps"]
        assert result["error"]["message"]
        assert result["recovery_action"]
