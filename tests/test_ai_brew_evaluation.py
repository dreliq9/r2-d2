from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path

import pytest

from swu_mcp.ai_brew_service import AIBrewService
from swu_mcp.ai_brew_session import BrewPersistenceError, BrewSessionStore
from swu_mcp.card_service import CardService
from swu_mcp.collection_service import CollectionService
from swu_mcp.config import Settings
from swu_mcp.deck_service import DeckService


def _card(
    set_code: str,
    number: str,
    name: str,
    card_type: str,
    *,
    subtitle: str | None = None,
    aspects: list[str] | None = None,
    front_text: str = "",
    keywords: list[str] | None = None,
    cost: str | None = None,
    arenas: list[str] | None = None,
) -> dict[str, object]:
    return {
        "Set": set_code,
        "Number": number,
        "Name": name,
        "Subtitle": subtitle,
        "Type": card_type,
        "Aspects": aspects or [],
        "Traits": ["JEDI"],
        "FrontText": front_text,
        "Keywords": keywords or [],
        "Cost": cost,
        "Arenas": arenas or [],
    }


@pytest.fixture
def evaluation_components(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    cards = [
        _card(
            "TST",
            "001",
            "Evaluation Leader",
            "Leader",
            subtitle="Mentor",
            aspects=["Vigilance", "Heroism"],
        ),
        _card("TST", "002", "Evaluation Base", "Base", aspects=["Vigilance"]),
    ]
    for number in range(3, 21):
        front_text = "When Played: Draw a card." if number == 3 else "Defeat a unit." if number == 4 else ""
        cards.append(
            _card(
                "TST",
                f"{number:03d}",
                "Enabler Unit" if number == 3 else "Payoff Unit" if number == 4 else f"Support Unit {number}",
                "Unit",
                aspects=["Vigilance", "Heroism"],
                front_text=front_text,
                keywords=["Sentinel"] if number == 5 else [],
                cost=str(1 + number % 3),
                arenas=["Ground"],
            )
        )
    cards.extend(
        [
            _card(
                "TST",
                "021",
                "Off Aspect Candidate",
                "Unit",
                aspects=["Aggression"],
                cost="2",
            ),
            _card(
                "TST",
                "022",
                "Evaluation Partner",
                "Leader",
                subtitle="Ally",
                aspects=["Command", "Heroism"],
            ),
            _card("TST", "023", "Evaluation Token", "Token", aspects=["Vigilance"]),
            _card(
                "TST",
                "024",
                "Sideboard Replacement",
                "Unit",
                aspects=["Vigilance", "Heroism"],
                cost="2",
            ),
        ]
    )
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(cards), encoding="utf-8")
    collection_path = tmp_path / "collection.json"
    collection_path.write_text(
        json.dumps(
            {
                "entries": [
                    {"set_code": "TST", "card_number": "001", "count": 1, "foil_count": 0},
                    {"set_code": "TST", "card_number": "002", "count": 1, "foil_count": 0},
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
    return {
        "service": AIBrewService(
            card_service,
            collection_service,
            DeckService(card_service, collection_service=collection_service),
            BrewSessionStore(tmp_path / "brews"),
        ),
        "collection_path": collection_path,
    }


def _start(service: AIBrewService, **overrides: object) -> dict[str, object]:
    request = {
        "format_name": "premier",
        "leader_names": ["Evaluation Leader - Mentor"],
        "base_name": "Evaluation Base",
        "theme": "resilient Jedi midrange",
        "target_matchups": ["aggro"],
        "only_owned": False,
    }
    request.update(overrides)
    return service.start_brew(**request)  # type: ignore[arg-type]


def _complete_revision(service: AIBrewService, session_id: str) -> dict[str, object]:
    additions = [
        {"printing_id": f"TST/{number:03d}", "quantity": 2 if number == 19 else 3}
        for number in range(3, 20)
    ]
    return service.record_decisions(
        session_id=session_id,
        expected_revision=0,
        additions=additions,
        rationale="Record the complete candidate deck for advisory evaluation.",
    )


def _categories() -> list[dict[str, object]]:
    return [
        {
            "name": "enabler",
            "printing_ids": ["TST/003", "TST/004"],
            "kind": "enabler",
        },
        {
            "name": "payoff",
            "printing_ids": ["TST/004", "TST/005"],
            "kind": "payoff",
        },
    ]


def _owned_complete_collection() -> dict[str, object]:
    entries = [
        {"set_code": "TST", "card_number": "001", "count": 1, "foil_count": 0},
        {"set_code": "TST", "card_number": "002", "count": 1, "foil_count": 0},
    ]
    entries.extend(
        {
            "set_code": "TST",
            "card_number": f"{number:03d}",
            "count": 2 if number == 19 else 3,
            "foil_count": 0,
        }
        for number in range(3, 20)
    )
    return {"entries": entries}


def test_evaluation_is_advisory_reproducible_and_exposes_its_model_boundaries(
    evaluation_components: dict[str, object]
) -> None:
    service = evaluation_components["service"]
    started = _start(service)
    assert started["status"] == "ok"
    assert _complete_revision(service, started["session_id"])["status"] == "ok"
    before = service.store.load(started["session_id"])
    original_revision = deepcopy(before.revisions[1].model_dump(mode="json"))

    first = service.evaluate_brew(
        session_id=started["session_id"],
        turn_horizons=[1, 3],
        mulligan_redraws=1,
        simulation_seed=17,
        simulation_count=31,
        probability_categories=_categories(),
        candidate_swaps=[
            {
                "suggestion_id": "replace-enabler",
                "adds": [{"printing_id": "TST/020", "quantity": 1}],
                "cuts": [{"printing_id": "TST/003", "quantity": 1}],
            }
        ],
    )
    second = service.evaluate_brew(
        session_id=started["session_id"],
        turn_horizons=[1, 3],
        mulligan_redraws=1,
        simulation_seed=17,
        simulation_count=31,
        probability_categories=_categories(),
        candidate_swaps=[
            {
                "suggestion_id": "replace-enabler",
                "adds": [{"printing_id": "TST/020", "quantity": 1}],
                "cuts": [{"printing_id": "TST/003", "quantity": 1}],
            }
        ],
    )

    stored = service.store.load(started["session_id"])
    assert first["status"] == "ok"
    assert first["revision"] == 1
    assert first["report_id"] != second["report_id"]
    assert [report.revision for report in stored.reports] == [1, 1]
    assert stored.current_revision == 1
    assert stored.revisions[1].model_dump(mode="json") == original_revision
    assert stored.stage == "evaluating"
    assert first["hard_constraints"] == first["validation"]
    assert set(first["objective_vector"]) == {
        "legality",
        "plan_reliability",
        "curve_quality",
        "interaction",
        "card_advantage",
        "resilience",
        "synergy",
        "matchup_fit",
    }

    enabler = first["probabilities"]["categories"][0]
    pair = first["probabilities"]["enabler_payoff"][0]
    assert enabler["population"] == 50
    assert enabler["successes"] == 6
    assert enabler["by_turn"]["1"]["draws"] == 7
    assert enabler["opening_hand"]["formula"] == (
        "1 - C(population - successes, draws) / C(population, draws)"
    )
    assert enabler["opening_hand"]["result"] == pytest.approx(
        1 - math.comb(44, 6) / math.comb(50, 6)
    )
    assert enabler["by_turn"]["1"]["result"] == pytest.approx(
        1 - math.comb(44, 7) / math.comb(50, 7)
    )
    assert enabler["by_turn"]["1"]["assumptions"]
    assert any(
        "one additional card is seen per turn" in assumption.lower()
        for assumption in enabler["by_turn"]["1"]["assumptions"]
    )
    assert pair["overlap"] == 3
    assert pair["formula"] == (
        "1 - C(population - enablers, draws) / C(population, draws) "
        "- C(population - payoffs, draws) / C(population, draws) "
        "+ C(population - (enablers + payoffs - overlap), draws) / C(population, draws)"
    )
    assert pair["by_turn"]["1"]["result"] == pytest.approx(
        1 - 2 * math.comb(44, 7) / math.comb(50, 7) + math.comb(41, 7) / math.comb(50, 7)
    )
    assert enabler["mulligan"]["is_approximation"] is True
    assert enabler["mulligan"]["method"] == "independent_full_redraw_approximation"
    assert first["simulation"] == second["simulation"]
    assert first["simulation"]["categories"]["enabler"]["turns"]["1"]["wilson_interval"]
    assert any("finite-sample" in item.lower() for item in first["simulation"]["limitations"])
    assert any("does not model" in item.lower() for item in first["simulation"]["limitations"])
    assert first["simulation"]["draw_schedule"] == {
        "opening_hand": 6,
        "additional_cards_seen_per_turn": 1,
    }

    assert first["goldfish"]["games"] == 31
    assert first["goldfish"]["seed"] == 17
    assert "Goldfish report checks opening hand texture only." in first["goldfish"]["limitations"]
    assert any("Unsupported mechanics are not modeled" in item for item in first["limitations"])

    suggestion = first["candidate_swaps"][0]
    assert suggestion["suggestion_id"] == "replace-enabler"
    assert suggestion["accepted"] is False
    assert set(suggestion["objective_deltas"]) == set(first["objective_vector"])
    assert "enabler" in suggestion["probability_deltas"]
    assert isinstance(suggestion["pareto_efficient"], bool)
    advisory_keys = {
        "hard_constraints",
        "validation",
        "analysis",
        "objective_vector",
        "objective_details",
        "probabilities",
        "simulation",
        "goldfish",
        "limitations",
        "candidate_swaps",
        "collection",
    }
    assert stored.reports[0].result == {key: first[key] for key in advisory_keys}
    assert stored.reports[0].result["collection"] == first["collection"]
    assert {key: first[key] for key in advisory_keys} == {
        key: second[key] for key in advisory_keys
    }


def test_historical_evaluation_is_persisted_without_rewinding_current_workflow(
    evaluation_components: dict[str, object]
) -> None:
    service = evaluation_components["service"]
    started = _start(service)
    assert _complete_revision(service, started["session_id"])["status"] == "ok"
    report = service.evaluate_brew(session_id=started["session_id"])
    assert report["status"] == "ok"
    advanced = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=1,
        additions=[{"printing_id": "TST/020", "quantity": 1}],
        cuts=[{"printing_id": "TST/019", "quantity": 1}],
        rationale="Create a later revision after the evaluation.",
    )
    assert advanced["status"] == "ok"

    historical = service.evaluate_brew(session_id=started["session_id"], revision=1)

    stored = service.store.load(started["session_id"])
    assert historical["status"] == "ok"
    assert historical["revision"] == 1
    assert stored.reports[-1].report_id == historical["report_id"]
    assert stored.reports[-1].revision == 1
    assert stored.current_revision == 2
    assert stored.stage == "revising"
    assert report["revision"] != stored.current_revision


def test_evaluation_diagnoses_collection_drift_without_blocking_read_only_report(
    evaluation_components: dict[str, object]
) -> None:
    service = evaluation_components["service"]
    collection_path = evaluation_components["collection_path"]
    started = _start(service, only_owned=True)
    collection_path.write_text(json.dumps({"entries": []}), encoding="utf-8")

    result = service.evaluate_brew(session_id=started["session_id"])

    assert result["status"] == "ok"
    assert result["collection"]["stale"] is True
    assert result["revision"] == 0
    stored = service.store.load(started["session_id"])
    assert stored.current_revision == 0
    assert stored.reports[-1].result["collection"] == result["collection"]


def test_incomplete_revision_has_no_advisory_objectives_or_goldfish(
    evaluation_components: dict[str, object]
) -> None:
    service = evaluation_components["service"]
    started = _start(service)

    result = service.evaluate_brew(
        session_id=started["session_id"],
        probability_categories=_categories(),
    )

    assert result["status"] == "ok"
    assert result["goldfish"]["available"] is False
    assert result["objective_vector"]["legality"] == 0.0
    for objective in (
        "plan_reliability",
        "curve_quality",
        "interaction",
        "card_advantage",
        "resilience",
        "synergy",
        "matchup_fit",
    ):
        assert result["objective_vector"][objective] is None
        assert any(objective in limitation for limitation in result["limitations"])


def test_invalid_candidates_are_unavailable_without_suppressing_valid_pareto_frontier(
    evaluation_components: dict[str, object]
) -> None:
    service = evaluation_components["service"]
    started = _start(service)
    assert _complete_revision(service, started["session_id"])["status"] == "ok"
    before = service.store.load(started["session_id"])

    result = service.evaluate_brew(
        session_id=started["session_id"],
        probability_categories=_categories(),
        objective_directions={"curve_quality": "max", "plan_reliability": "max"},
        candidate_swaps=[
            {
                "suggestion_id": "valid-tradeoff",
                "adds": [{"printing_id": "TST/020", "quantity": 1}],
                "cuts": [{"printing_id": "TST/003", "quantity": 1}],
            },
            {
                "suggestion_id": "off-aspect",
                "adds": [{"printing_id": "TST/021", "quantity": 1}],
                "cuts": [{"printing_id": "TST/019", "quantity": 1}],
            },
        ],
    )

    assert result["status"] == "ok"
    valid, invalid = result["candidate_swaps"]
    assert valid["accepted"] is False
    assert valid["objective_deltas"]["curve_quality"] > 0
    assert valid["objective_deltas"]["plan_reliability"] < 0
    assert valid["pareto_status"] == "frontier"
    assert valid["pareto_efficient"] is True
    assert invalid["accepted"] is False
    assert invalid["pareto_status"] == "unavailable"
    assert invalid["pareto_efficient"] is False
    assert invalid["objective_vector"] == {key: None for key in result["objective_vector"]}
    assert any("Off-aspect" in item for item in invalid["hard_constraints"]["errors"])
    stored = service.store.load(started["session_id"])
    assert stored.revisions == before.revisions
    assert len(stored.decisions) == len(before.decisions)


@pytest.mark.parametrize(
    ("suggestion_id", "printing_id", "expected_error"),
    [
        ("unknown-printing", "TST/999", "Could not resolve exact printing"),
        ("wrong-type", "TST/022", "Only Unit, Event, or Upgrade"),
        ("off-aspect", "TST/021", "Off-aspect"),
        ("premier-copy-limit", "TST/003", "Canonical copy limit is 3"),
    ],
)
def test_candidates_apply_real_session_hard_constraints(
    evaluation_components: dict[str, object],
    suggestion_id: str,
    printing_id: str,
    expected_error: str,
) -> None:
    service = evaluation_components["service"]
    started = _start(service)
    assert _complete_revision(service, started["session_id"])["status"] == "ok"

    result = service.evaluate_brew(
        session_id=started["session_id"],
        candidate_swaps=[
            {
                "suggestion_id": suggestion_id,
                "adds": [{"printing_id": printing_id, "quantity": 1}],
                "cuts": [{"printing_id": "TST/019", "quantity": 1}],
            }
        ],
    )

    candidate = result["candidate_swaps"][0]
    assert candidate["accepted"] is False
    assert candidate["pareto_status"] == "unavailable"
    assert candidate["pareto_efficient"] is False
    assert any(expected_error in item for item in candidate["hard_constraints"]["errors"])


def test_candidate_swaps_apply_additions_and_cuts_to_the_requested_sideboard_zone(
    evaluation_components: dict[str, object]
) -> None:
    service = evaluation_components["service"]
    started = _start(service)
    additions = [
        *[
            {"printing_id": f"TST/{number:03d}", "quantity": 2 if number == 19 else 3}
            for number in range(3, 20)
        ],
        {"printing_id": "TST/020", "quantity": 1, "zone": "sideboard"},
    ]
    assert service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=additions,
        rationale="Create a legal main deck with one sideboard card.",
    )["status"] == "ok"

    result = service.evaluate_brew(
        session_id=started["session_id"],
        candidate_swaps=[
            {
                "suggestion_id": "sideboard-only-swap",
                "adds": [
                    {"printing_id": "TST/024", "quantity": 1, "zone": "sideboard"}
                ],
                "cuts": [
                    {"printing_id": "TST/020", "quantity": 1, "zone": "sideboard"}
                ],
            }
        ],
    )

    candidate = result["candidate_swaps"][0]
    assert result["status"] == "ok"
    assert candidate["hard_constraints"]["legal"] is True
    assert candidate["pareto_status"] != "unavailable"
    persisted = service.store.load(started["session_id"])
    assert [entry["lookup_id"] for entry in persisted.revisions[1].sideboard] == ["TST/020"]


@pytest.mark.parametrize(
    ("overrides", "expected_message"),
    [
        ({"simulation_count": 10_001}, "simulation_count must be at most 10000"),
        ({"turn_horizons": list(range(21))}, "turn_horizons may contain at most 20"),
        ({"turn_horizons": [81]}, "turn horizon must be at most 80"),
        (
            {
                "probability_categories": [
                    {"name": f"category-{index}", "printing_ids": ["TST/003"]}
                    for index in range(33)
                ]
            },
            "probability_categories may contain at most 32",
        ),
        (
            {
                "candidate_swaps": [
                    {"suggestion_id": f"swap-{index}", "adds": [], "cuts": []}
                    for index in range(21)
                ]
            },
            "candidate_swaps may contain at most 20",
        ),
        ({"mulligan_redraws": 11}, "mulligan_redraws must be at most 10"),
    ],
)
def test_evaluation_workload_caps_fail_before_persisting_a_report(
    evaluation_components: dict[str, object],
    overrides: dict[str, object],
    expected_message: str,
) -> None:
    service = evaluation_components["service"]
    started = _start(service)
    target = service.store.root / f"{started['session_id']}.json"
    before = target.read_bytes()

    result = service.evaluate_brew(
        session_id=started["session_id"],
        **overrides,
    )

    assert result["status"] == "fail"
    assert expected_message in result["error"]["message"]
    assert result["diagnostics"]
    assert result["next_steps"]
    assert target.read_bytes() == before


@pytest.mark.parametrize(
    ("overrides", "expected_message"),
    [
        (
            {
                "probability_categories": [
                    {
                        "name": "oversized-category",
                        "printing_ids": [f"TST/{number:03d}" for number in range(1, 82)],
                    }
                ]
            },
            "printing_ids may contain at most 80",
        ),
        (
            {
                "candidate_swaps": [
                    {
                        "suggestion_id": "oversized-swap",
                        "adds": [
                            {"printing_id": "TST/003", "quantity": 1}
                            for _ in range(81)
                        ],
                        "cuts": [],
                    }
                ]
            },
            "candidate swap adds may contain at most 80",
        ),
    ],
)
def test_nested_evaluation_workload_caps_fail_closed(
    evaluation_components: dict[str, object],
    overrides: dict[str, object],
    expected_message: str,
) -> None:
    service = evaluation_components["service"]
    started = _start(service)

    result = service.evaluate_brew(session_id=started["session_id"], **overrides)

    assert result["status"] == "fail"
    assert expected_message in result["error"]["message"]
    assert service.store.load(started["session_id"]).reports == []


def test_only_owned_candidate_conflicts_are_read_only_hard_constraints(
    evaluation_components: dict[str, object]
) -> None:
    service = evaluation_components["service"]
    collection_path = evaluation_components["collection_path"]
    collection_path.write_text(json.dumps(_owned_complete_collection()), encoding="utf-8")
    started = _start(service, only_owned=True)
    assert _complete_revision(service, started["session_id"])["status"] == "ok"
    before = service.store.load(started["session_id"])

    result = service.evaluate_brew(
        session_id=started["session_id"],
        candidate_swaps=[
            {
                "suggestion_id": "unowned-card",
                "adds": [{"printing_id": "TST/020", "quantity": 1}],
                "cuts": [{"printing_id": "TST/003", "quantity": 1}],
            }
        ],
    )

    candidate = result["candidate_swaps"][0]
    assert candidate["accepted"] is False
    assert candidate["pareto_status"] == "unavailable"
    assert candidate["hard_constraints"]["collection_conflicts"] == [
        {"printing_id": "TST/020", "requested": 1, "owned": 0}
    ]
    stored = service.store.load(started["session_id"])
    assert stored.revisions == before.revisions
    assert len(stored.decisions) == len(before.decisions)


def test_stale_owned_collection_disables_all_candidate_comparison(
    evaluation_components: dict[str, object]
) -> None:
    service = evaluation_components["service"]
    collection_path = evaluation_components["collection_path"]
    initial_collection = _owned_complete_collection()
    initial_collection["entries"].append(
        {"set_code": "TST", "card_number": "020", "count": 1, "foil_count": 0}
    )
    collection_path.write_text(json.dumps(initial_collection), encoding="utf-8")
    started = _start(service, only_owned=True)
    assert _complete_revision(service, started["session_id"])["status"] == "ok"
    service.collection_service._load_from_disk()
    collection_path.write_text(json.dumps({"entries": []}), encoding="utf-8")

    result = service.evaluate_brew(
        session_id=started["session_id"],
        probability_categories=_categories(),
        candidate_swaps=[
            {
                "suggestion_id": "cached-owned-candidate",
                "adds": [{"printing_id": "TST/020", "quantity": 1}],
                "cuts": [{"printing_id": "TST/003", "quantity": 1}],
            }
        ],
    )

    candidate = result["candidate_swaps"][0]
    assert result["status"] == "ok"
    assert result["collection"]["stale"] is True
    assert candidate["accepted"] is False
    assert candidate["pareto_status"] == "unavailable"
    assert candidate["pareto_efficient"] is False
    assert candidate["objective_vector"] == {key: None for key in result["objective_vector"]}
    assert candidate["objective_deltas"] == {key: None for key in result["objective_vector"]}
    assert candidate["probability_deltas"] == {"enabler": None, "payoff": None}
    assert any(
        "stale" in diagnostic.lower() and "ownership" in diagnostic.lower()
        for diagnostic in candidate["diagnostics"]
    )
    assert any(
        "only-owned collection provenance is stale" in limitation.lower()
        for limitation in result["limitations"]
    )
    stored = service.store.load(started["session_id"])
    assert stored.reports[-1].result["collection"]["stale"] is True
    assert stored.reports[-1].result["candidate_swaps"] == [candidate]
    assert any(
        "only-owned collection provenance is stale" in limitation.lower()
        for limitation in stored.reports[-1].result["limitations"]
    )


@pytest.mark.parametrize(
    ("candidate_swaps", "expected_message"),
    [
        (
            [
                {"suggestion_id": "same", "adds": [], "cuts": []},
                {"suggestion_id": "same", "adds": [], "cuts": []},
            ],
            "unique",
        ),
        (
            [{"suggestion_id": "baseline", "adds": [], "cuts": []}],
            "reserved",
        ),
    ],
)
def test_invalid_candidate_ids_fail_before_report_or_stage_change(
    evaluation_components: dict[str, object],
    candidate_swaps: list[dict[str, object]],
    expected_message: str,
) -> None:
    service = evaluation_components["service"]
    started = _start(service)
    target = service.store.root / f"{started['session_id']}.json"
    before = target.read_bytes()

    result = service.evaluate_brew(
        session_id=started["session_id"],
        candidate_swaps=candidate_swaps,  # type: ignore[arg-type]
    )

    assert result["status"] == "fail"
    assert expected_message in result["error"]["message"].lower()
    assert target.read_bytes() == before
    stored = BrewSessionStore(service.store.root).load(started["session_id"])
    assert stored.reports == []
    assert stored.stage == "planning"


def test_twin_suns_candidate_enforces_singleton_canonical_limit(
    evaluation_components: dict[str, object]
) -> None:
    service = evaluation_components["service"]
    started = _start(
        service,
        format_name="twin_suns",
        leader_names=["Evaluation Leader - Mentor", "Evaluation Partner - Ally"],
    )
    assert service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=[{"printing_id": "TST/003", "quantity": 1}],
        rationale="Add the singleton card before checking a duplicate candidate.",
    )["status"] == "ok"

    result = service.evaluate_brew(
        session_id=started["session_id"],
        candidate_swaps=[
            {
                "suggestion_id": "duplicate-singleton",
                "adds": [{"printing_id": "TST/003", "quantity": 1}],
                "cuts": [],
            }
        ],
    )

    candidate = result["candidate_swaps"][0]
    assert candidate["pareto_status"] == "unavailable"
    assert any("Canonical copy limit is 1" in item for item in candidate["hard_constraints"]["errors"])


def test_evaluated_report_can_be_explicitly_accepted_as_stale_evidence(
    evaluation_components: dict[str, object]
) -> None:
    service = evaluation_components["service"]
    started = _start(service)
    assert _complete_revision(service, started["session_id"])["status"] == "ok"
    report = service.evaluate_brew(session_id=started["session_id"])
    assert report["status"] == "ok"
    assert service.record_decisions(
        session_id=started["session_id"],
        expected_revision=1,
        additions=[{"printing_id": "TST/020", "quantity": 1}],
        cuts=[{"printing_id": "TST/019", "quantity": 1}],
        rationale="Advance past the evaluated revision.",
    )["status"] == "ok"

    result = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=2,
        additions=[{"printing_id": "TST/019", "quantity": 1}],
        cuts=[{"printing_id": "TST/020", "quantity": 1}],
        rationale="Explicitly retain the prior evaluation as stale provenance.",
        advisory_report_id=report["report_id"],
        accept_stale_evidence=True,
    )

    assert result["status"] == "ok"
    assert service.store.load(started["session_id"]).decisions[-1].accepted_stale_evidence is True


def test_save_failure_leaves_no_partial_report_or_stage_change(
    evaluation_components: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    service = evaluation_components["service"]
    started = _start(service)
    target = service.store.root / f"{started['session_id']}.json"
    before = target.read_bytes()

    def fail_save(_session: object) -> None:
        raise BrewPersistenceError("injected report save failure")

    monkeypatch.setattr(service.store, "save", fail_save)
    result = service.evaluate_brew(session_id=started["session_id"])

    assert result["status"] == "fail"
    assert target.read_bytes() == before
    persisted = BrewSessionStore(service.store.root).load(started["session_id"])
    assert persisted.reports == []
    assert persisted.stage == "planning"
