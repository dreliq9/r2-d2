from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from swu_mcp import server
from swu_mcp.ai_brew_service import AIBrewService
from swu_mcp.ai_brew_session import BrewSessionStore
from swu_mcp.card_service import CardService
from swu_mcp.collection_service import CollectionService
from swu_mcp.config import Settings
from swu_mcp.deck_service import DeckService
from swu_mcp.types import (
    BrewCardChange,
    BrewContextFilters,
    BrewPackage,
    BrewProbabilityCategory,
    BrewRoleTargets,
    BrewSwapSuggestion,
)


def _card(
    number: int,
    name: str,
    card_type: str,
    *,
    subtitle: str | None = None,
    aspects: list[str] | None = None,
    cost: str | None = None,
) -> dict[str, object]:
    return {
        "Set": "E2E",
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


class TrapAutomaticDeckService(DeckService):
    """Real deck operations with automatic deck-selection paths forbidden."""

    def __init__(self, card_service: CardService, collection_service: CollectionService) -> None:
        super().__init__(card_service, collection_service=collection_service)
        self.automatic_calls: list[str] = []

    def _unexpected_automatic_call(self, name: str) -> None:
        self.automatic_calls.append(name)
        pytest.fail(f"AI-led workflow must not call DeckService.{name}.")

    def generate_deck(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._unexpected_automatic_call("generate_deck")
        return {}

    def optimize_deck(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._unexpected_automatic_call("optimize_deck")
        return {}

    def suggest_cards(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._unexpected_automatic_call("suggest_cards")
        return {}


@pytest.fixture
def workflow_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, object]:
    cards = [
        _card(
            1,
            "Workflow Leader",
            "Leader",
            subtitle="Mentor",
            aspects=["Vigilance", "Heroism"],
        ),
        _card(
            2,
            "Workflow Partner",
            "Leader",
            subtitle="Ally",
            aspects=["Command", "Heroism"],
        ),
        _card(3, "Workflow Base", "Base", aspects=["Vigilance"]),
    ]
    cards.extend(
        _card(
            number,
            f"Workflow Unit {number:03d}",
            "Unit",
            aspects=["Vigilance", "Heroism"],
            cost=str(1 + number % 4),
        )
        for number in range(4, 87)
    )
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(cards), encoding="utf-8")
    collection_path = tmp_path / "collection.json"
    collection_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "set_code": "E2E",
                        "card_number": f"{number:03d}",
                        "count": 3 if number >= 4 else 1,
                        "foil_count": 0,
                    }
                    for number in range(1, 86)
                ]
            }
        ),
        encoding="utf-8",
    )
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(
        "swu_mcp.card_service.settings",
        Settings(card_catalog_path=str(catalog_path), cache_dir=cache_dir),
    )
    card_service = CardService()
    collection_service = CollectionService(collection_path)
    deck_service = TrapAutomaticDeckService(card_service, collection_service)
    store_path = tmp_path / "brews"
    return {
        "card_service": card_service,
        "catalog_path": catalog_path,
        "cache_dir": cache_dir,
        "collection_path": collection_path,
        "collection_service": collection_service,
        "deck_service": deck_service,
        "service": AIBrewService(
            card_service,
            collection_service,
            deck_service,
            BrewSessionStore(store_path),
        ),
        "store_path": store_path,
    }


def _context_evidence(session_id: str) -> dict[str, dict[str, object]]:
    context = server.swu_get_brew_context(
        session_id=session_id,
        intent="candidates",
        filters=BrewContextFilters(aspects=["Vigilance", "Heroism"], minimum_owned=1),
        limit=100,
    )
    assert context["status"] == "ok"
    return {str(item["printing_id"]): item for item in context["cards"]}


def _changes(printing_ids: list[str], quantities: dict[str, int] | None = None) -> list[BrewCardChange]:
    quantities = quantities or {}
    return [
        BrewCardChange(card_id=printing_id, quantity=quantities.get(printing_id, 1))
        for printing_id in printing_ids
    ]


def _without_report_ids_and_timestamps(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _without_report_ids_and_timestamps(item)
            for key, item in value.items()
            if key not in {"report_id", "created_at", "updated_at", "timestamp"}
        }
    if isinstance(value, list):
        return [_without_report_ids_and_timestamps(item) for item in value]
    return value


def _session_snapshot(service: AIBrewService, session_id: str) -> dict[str, object]:
    return service.store.load(session_id).model_dump(mode="json")


def _deck_quantity(entries: list[dict[str, object]], printing_id: str) -> int:
    return next(
        int(entry["quantity"])
        for entry in entries
        if str(entry["lookup_id"]) == printing_id
    )


def test_owned_premier_wrapper_workflow_is_reproducible_finalized_and_durable(
    workflow_components: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    service = workflow_components["service"]
    deck_service = workflow_components["deck_service"]
    monkeypatch.setattr(server, "ai_brew_service", service)

    started = server.swu_start_ai_brew(
        format_name="premier",
        leader_names=["Workflow Leader - Mentor"],
        base_name="Workflow Base",
        theme="owned resilient Jedi midrange",
        only_owned=True,
        target_matchups=["aggro"],
        meta_context={"season": "acceptance"},
        session_id="workflow-premier",
    )
    assert started["status"] == "ok"
    session_id = str(started["session_id"])
    assert started["collection_snapshot"]["path"] == str(workflow_components["collection_path"])
    evidence = _context_evidence(session_id)
    premier_ids = [f"E2E/{number:03d}" for number in range(4, 21)]
    quantities = {printing_id: 3 for printing_id in premier_ids[:-1]}
    quantities[premier_ids[-1]] = 2
    assert set(premier_ids) <= set(evidence)
    assert {"E2E/021", "E2E/022"} <= set(evidence)
    assert all(evidence[printing_id]["ownership"]["owned"] for printing_id in premier_ids)

    first_decision = server.swu_record_brew_decisions(
        session_id=session_id,
        expected_revision=0,
        thesis="Use owned Jedi units to stabilize early and win the midgame.",
        packages=[BrewPackage(name="resilient_jedi", target=18)],
        role_targets=BrewRoleTargets({"defense": 8, "midgame": 20}),
        additions=_changes(premier_ids, quantities),
        rationale="Record each context-evidenced owned Premier card explicitly.",
        evidence_ids=premier_ids,
    )
    assert first_decision["status"] == "ok"
    assert first_decision["revision"] == 1

    before_under_owned_rejection = _session_snapshot(service, session_id)
    under_owned = server.swu_record_brew_decisions(
        session_id=session_id,
        expected_revision=1,
        additions=[BrewCardChange(card_id="E2E/086", quantity=1)],
        cuts=[BrewCardChange(card_id="E2E/020", quantity=1)],
        rationale="This unowned candidate must not enter an owned brew.",
    )
    assert under_owned["status"] == "fail"
    assert under_owned["collection"]["conflicts"] == [
        {"printing_id": "E2E/086", "requested": 1, "owned": 0}
    ]
    assert _session_snapshot(service, session_id) == before_under_owned_rejection

    rejected_reports = [
        server.swu_evaluate_ai_brew(
            session_id=session_id,
            turn_horizons=[1, 3],
            simulation_seed=17,
            simulation_count=31,
            probability_categories=[
                BrewProbabilityCategory(
                    name="early_units",
                    printing_ids=premier_ids[:3],
                    kind="enabler",
                )
            ],
            candidate_swaps=[
                BrewSwapSuggestion(
                    suggestion_id="reject-one",
                    adds=[BrewCardChange(card_id="E2E/021", quantity=1)],
                    cuts=[BrewCardChange(card_id="E2E/020", quantity=1)],
                )
            ],
        ),
        server.swu_evaluate_ai_brew(
            session_id=session_id,
            turn_horizons=[1, 3],
            simulation_seed=17,
            simulation_count=31,
            probability_categories=[
                BrewProbabilityCategory(
                    name="early_units",
                    printing_ids=premier_ids[:3],
                    kind="enabler",
                )
            ],
            candidate_swaps=[
                BrewSwapSuggestion(
                    suggestion_id="reject-one",
                    adds=[BrewCardChange(card_id="E2E/021", quantity=1)],
                    cuts=[BrewCardChange(card_id="E2E/020", quantity=1)],
                )
            ],
        ),
    ]
    first_report, duplicate_report = rejected_reports
    assert first_report["status"] == duplicate_report["status"] == "ok"
    assert first_report["report_id"] != duplicate_report["report_id"]
    assert _without_report_ids_and_timestamps(first_report) == _without_report_ids_and_timestamps(
        duplicate_report
    )
    assert first_report["candidate_swaps"][0]["suggestion_id"] == "reject-one"
    assert first_report["candidate_swaps"][0]["accepted"] is False

    rejected = server.swu_record_brew_decisions(
        session_id=session_id,
        expected_revision=1,
        rejected_cards=[BrewCardChange(card_id="E2E/021", quantity=1)],
        rationale="Reject reject-one after its advisory comparison.",
        evidence_ids=["suggestion:reject-one"],
        advisory_report_id=first_report["report_id"],
    )
    assert rejected["status"] == "ok"
    assert rejected["revision"] == 2
    after_rejection = service.store.load(session_id)
    assert after_rejection.revisions[2].main_deck == after_rejection.revisions[1].main_deck
    assert after_rejection.revisions[2].rejected_cards[0]["lookup_id"] == "E2E/021"

    accepted_report = server.swu_evaluate_ai_brew(
        session_id=session_id,
        turn_horizons=[1, 3],
        simulation_seed=17,
        simulation_count=31,
        candidate_swaps=[
            BrewSwapSuggestion(
                suggestion_id="accept-one",
                adds=[BrewCardChange(card_id="E2E/022", quantity=1)],
                cuts=[BrewCardChange(card_id="E2E/020", quantity=1)],
            )
        ],
    )
    assert accepted_report["status"] == "ok"
    assert accepted_report["candidate_swaps"][0]["suggestion_id"] == "accept-one"
    assert accepted_report["candidate_swaps"][0]["accepted"] is False

    collection_path = workflow_components["collection_path"]
    collection_payload = json.loads(collection_path.read_text(encoding="utf-8"))
    collection_payload["acceptance_drift"] = "recorded-before-explicit-refresh"
    collection_path.write_text(json.dumps(collection_payload), encoding="utf-8")
    before_collection_drift_rejection = _session_snapshot(service, session_id)
    stale_collection = server.swu_record_brew_decisions(
        session_id=session_id,
        expected_revision=2,
        additions=[BrewCardChange(card_id="E2E/022", quantity=1)],
        cuts=[BrewCardChange(card_id="E2E/020", quantity=1)],
        rationale="Collection drift must fail closed before an accepted swap.",
        evidence_ids=["suggestion:accept-one"],
        advisory_report_id=accepted_report["report_id"],
    )
    assert stale_collection["status"] == "fail"
    assert stale_collection["collection"]["stale"] is True
    assert _session_snapshot(service, session_id) == before_collection_drift_rejection

    stale_advisory = server.swu_record_brew_decisions(
        session_id=session_id,
        expected_revision=2,
        rationale="Stale advisory evidence must fail closed.",
        advisory_report_id=first_report["report_id"],
    )
    assert stale_advisory["status"] == "fail"
    assert "bound to revision 1, not expected revision 2" in stale_advisory["error"]["message"]
    assert _session_snapshot(service, session_id) == before_collection_drift_rejection

    accepted = server.swu_record_brew_decisions(
        session_id=session_id,
        expected_revision=2,
        additions=[BrewCardChange(card_id="E2E/022", quantity=1)],
        cuts=[BrewCardChange(card_id="E2E/020", quantity=1)],
        rationale="Accept accept-one through an explicit add and cut decision.",
        evidence_ids=["suggestion:accept-one"],
        advisory_report_id=accepted_report["report_id"],
        refresh_collection=True,
    )
    assert accepted["status"] == "ok"
    assert accepted["revision"] == 3
    assert accepted["collection"]["stale"] is False
    after_accepted = service.store.load(session_id)
    assert _deck_quantity(after_accepted.revisions[3].main_deck, "E2E/022") == 1
    assert _deck_quantity(after_accepted.revisions[3].main_deck, "E2E/020") == 1
    assert [(entry["lookup_id"], entry["quantity"]) for entry in after_accepted.decisions[2].additions] == [
        ("E2E/022", 1)
    ]
    assert [(entry["lookup_id"], entry["quantity"]) for entry in after_accepted.decisions[2].cuts] == [
        ("E2E/020", 1)
    ]
    assert len(after_accepted.collection_refreshes) == 1

    before_stale_revision = _session_snapshot(service, session_id)
    stale = server.swu_record_brew_decisions(
        session_id=session_id,
        expected_revision=2,
        rationale="This stale revision must not be accepted.",
    )
    assert stale["status"] == "fail"
    assert "expected revision 2, but current revision is 3" in stale["error"]["message"]
    assert stale["recovery_action"]
    after_stale_revision = _session_snapshot(service, session_id)
    assert after_stale_revision == before_stale_revision
    assert after_stale_revision["current_revision"] == 3
    assert len(after_stale_revision["decisions"]) == 3
    assert len(after_stale_revision["reports"]) == 3
    assert after_stale_revision["finalization_receipts"] == []

    finalized = server.swu_finalize_ai_brew(session_id=session_id, expected_revision=3)
    assert finalized["status"] == "ok"
    assert finalized["validation"]["legal"] is True
    assert finalized["validation"]["counts"]["main_deck"] == 50
    assert finalized["plain_text"]["export_format"] == "plain_text"
    assert finalized["holoscan"]["export_format"] == "holoscan"
    assert finalized["plain_text"]["deck"]
    assert finalized["holoscan"]["deck"]
    assert finalized["collection"]["snapshot_hash"] == finalized["collection"]["current_hash"]
    assert finalized["receipt"]["collection"] == finalized["collection"]
    assert finalized["receipt"]["decision_history"] == finalized["decision_history"]

    fresh_card_service = CardService()
    fresh_collection_service = CollectionService(workflow_components["collection_path"])
    fresh_deck_service = TrapAutomaticDeckService(fresh_card_service, fresh_collection_service)
    fresh_service = AIBrewService(
        fresh_card_service,
        fresh_collection_service,
        fresh_deck_service,
        BrewSessionStore(workflow_components["store_path"]),
    )
    monkeypatch.setattr(server, "ai_brew_service", fresh_service)
    history = server.swu_get_brew_context(session_id=session_id, intent="revision-history")
    reloaded = fresh_service.store.load(session_id)
    assert history["status"] == "ok"
    assert history["current_revision"] == 3
    assert len(history["revisions"]) == 4
    assert reloaded.stage == "finalized"
    assert len(reloaded.decisions) == 3
    assert len(reloaded.reports) == 3
    assert len(reloaded.finalization_receipts) == 1
    assert {str(card["lookup_id"]) for card in reloaded.revisions[3].main_deck} <= set(evidence)
    assert _deck_quantity(reloaded.revisions[3].main_deck, "E2E/022") == 1
    assert _deck_quantity(reloaded.revisions[3].main_deck, "E2E/020") == 1
    assert reloaded.finalization_receipts[0] == finalized["receipt"]
    assert reloaded.decisions[1].advisory_report_id == first_report["report_id"]
    assert reloaded.decisions[2].advisory_report_id == accepted_report["report_id"]
    assert deck_service.automatic_calls == []
    assert fresh_deck_service.automatic_calls == []


def test_owned_twin_suns_wrapper_workflow_finalizes_a_singleton_deck(
    workflow_components: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    service = workflow_components["service"]
    deck_service = workflow_components["deck_service"]
    monkeypatch.setattr(server, "ai_brew_service", service)

    started = server.swu_start_ai_brew(
        format_name="twin_suns",
        leader_names=["Workflow Leader - Mentor", "Workflow Partner - Ally"],
        base_name="Workflow Base",
        theme="owned singleton Jedi midrange",
        only_owned=True,
        session_id="workflow-twin-suns",
    )
    assert started["status"] == "ok"
    session_id = str(started["session_id"])
    assert started["collection_snapshot"]["path"] == str(workflow_components["collection_path"])
    evidence = _context_evidence(session_id)
    singleton_ids = [f"E2E/{number:03d}" for number in range(4, 84)]
    assert len(singleton_ids) == 80
    assert set(singleton_ids) <= set(evidence)

    recorded = server.swu_record_brew_decisions(
        session_id=session_id,
        expected_revision=0,
        thesis="Use one owned copy of every context-evidenced Jedi unit.",
        packages=[BrewPackage(name="singleton_jedi", target=80)],
        role_targets=BrewRoleTargets({"midgame": 80}),
        additions=_changes(singleton_ids),
        rationale="Record each owned singleton card explicitly from context evidence.",
        evidence_ids=singleton_ids,
    )
    assert recorded["status"] == "ok"
    rejected_reports = [
        server.swu_evaluate_ai_brew(
            session_id=session_id,
            turn_horizons=[1, 3],
            simulation_seed=17,
            simulation_count=31,
            candidate_swaps=[
                BrewSwapSuggestion(
                    suggestion_id="twin-reject-one",
                    adds=[BrewCardChange(card_id="E2E/084", quantity=1)],
                    cuts=[BrewCardChange(card_id="E2E/083", quantity=1)],
                )
            ],
        ),
        server.swu_evaluate_ai_brew(
            session_id=session_id,
            turn_horizons=[1, 3],
            simulation_seed=17,
            simulation_count=31,
            candidate_swaps=[
                BrewSwapSuggestion(
                    suggestion_id="twin-reject-one",
                    adds=[BrewCardChange(card_id="E2E/084", quantity=1)],
                    cuts=[BrewCardChange(card_id="E2E/083", quantity=1)],
                )
            ],
        ),
    ]
    twin_first_report, twin_duplicate_report = rejected_reports
    assert twin_first_report["status"] == twin_duplicate_report["status"] == "ok"
    assert twin_first_report["report_id"] != twin_duplicate_report["report_id"]
    assert _without_report_ids_and_timestamps(twin_first_report) == _without_report_ids_and_timestamps(
        twin_duplicate_report
    )
    assert twin_first_report["candidate_swaps"][0]["accepted"] is False

    rejected = server.swu_record_brew_decisions(
        session_id=session_id,
        expected_revision=1,
        rejected_cards=[BrewCardChange(card_id="E2E/084", quantity=1)],
        rationale="Reject twin-reject-one without changing the singleton deck.",
        evidence_ids=["suggestion:twin-reject-one"],
        advisory_report_id=twin_first_report["report_id"],
    )
    assert rejected["status"] == "ok"
    assert rejected["revision"] == 2
    after_rejection = service.store.load(session_id)
    assert after_rejection.revisions[2].main_deck == after_rejection.revisions[1].main_deck

    accepted_report = server.swu_evaluate_ai_brew(
        session_id=session_id,
        turn_horizons=[1, 3],
        simulation_seed=17,
        simulation_count=31,
        candidate_swaps=[
            BrewSwapSuggestion(
                suggestion_id="twin-accept-one",
                adds=[BrewCardChange(card_id="E2E/085", quantity=1)],
                cuts=[BrewCardChange(card_id="E2E/083", quantity=1)],
            )
        ],
    )
    assert accepted_report["status"] == "ok"
    assert accepted_report["candidate_swaps"][0]["accepted"] is False

    accepted = server.swu_record_brew_decisions(
        session_id=session_id,
        expected_revision=2,
        additions=[BrewCardChange(card_id="E2E/085", quantity=1)],
        cuts=[BrewCardChange(card_id="E2E/083", quantity=1)],
        rationale="Accept twin-accept-one through an explicit singleton add and cut.",
        evidence_ids=["suggestion:twin-accept-one"],
        advisory_report_id=accepted_report["report_id"],
    )
    assert accepted["status"] == "ok"
    assert accepted["revision"] == 3
    accepted_session = service.store.load(session_id)
    assert _deck_quantity(accepted_session.revisions[3].main_deck, "E2E/085") == 1
    assert all(
        str(card["lookup_id"]) != "E2E/083"
        for card in accepted_session.revisions[3].main_deck
    )

    before_stale_revision = _session_snapshot(service, session_id)
    stale = server.swu_record_brew_decisions(
        session_id=session_id,
        expected_revision=2,
        rationale="This stale Twin Suns revision must not be accepted.",
    )
    assert stale["status"] == "fail"
    assert "expected revision 2, but current revision is 3" in stale["error"]["message"]
    assert _session_snapshot(service, session_id) == before_stale_revision

    finalized = server.swu_finalize_ai_brew(session_id=session_id, expected_revision=3)
    assert finalized["status"] == "ok"
    assert finalized["validation"]["legal"] is True
    assert finalized["validation"]["counts"] == {
        "leaders": 2,
        "bases": 1,
        "main_deck": 80,
        "sideboard": 0,
    }
    assert finalized["plain_text"]["export_format"] == "plain_text"
    assert finalized["holoscan"]["export_format"] == "holoscan"
    assert finalized["receipt"]["collection"] == finalized["collection"]
    assert finalized["receipt"]["decision_history"] == finalized["decision_history"]

    fresh_card_service = CardService()
    fresh_collection_service = CollectionService(workflow_components["collection_path"])
    fresh_deck_service = TrapAutomaticDeckService(fresh_card_service, fresh_collection_service)
    fresh_service = AIBrewService(
        fresh_card_service,
        fresh_collection_service,
        fresh_deck_service,
        BrewSessionStore(workflow_components["store_path"]),
    )
    monkeypatch.setattr(server, "ai_brew_service", fresh_service)
    history = server.swu_get_brew_context(session_id=session_id, intent="revision-history")
    reloaded = fresh_service.store.load(session_id)
    assert history["status"] == "ok"
    assert history["current_revision"] == 3
    assert len(history["revisions"]) == 4
    assert len(reloaded.decisions) == 3
    assert len(reloaded.reports) == 3
    assert len(reloaded.finalization_receipts) == 1
    assert _deck_quantity(reloaded.revisions[3].main_deck, "E2E/085") == 1
    assert reloaded.finalization_receipts[0] == finalized["receipt"]
    assert deck_service.automatic_calls == []
    assert fresh_deck_service.automatic_calls == []
