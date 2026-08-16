from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from swu_mcp import server
from swu_mcp.ai_brew_service import AIBrewService, _collection_hash
from swu_mcp.ai_brew_session import (
    BrewReport,
    BrewSessionStore,
    canonical_revision_hash,
)
from swu_mcp.card_service import CardService
from swu_mcp.collection_service import CollectionService
from swu_mcp.config import Settings
from swu_mcp.deck_service import DeckService
from swu_mcp.types import BrewCardChange, BrewContextFilters


def _card(
    set_code: str,
    number: str,
    name: str,
    card_type: str,
    *,
    subtitle: str | None = None,
    aspects: list[str] | None = None,
    traits: list[str] | None = None,
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
        "Traits": traits or [],
        "FrontText": front_text,
        "Keywords": keywords or [],
        "Cost": cost,
        "Arenas": arenas or [],
    }


@pytest.fixture
def brew_components(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    cards = [
        _card(
            "SOR", "001", "Luke Skywalker", "Leader", subtitle="Faithful Friend",
            aspects=["Vigilance", "Heroism"], traits=["JEDI"],
            front_text="Action: Use the Force.",
        ),
        _card(
            "SOR", "002", "Leia Organa", "Leader", subtitle="Rebel Ally",
            aspects=["Command", "Heroism"], traits=["REBEL"],
            front_text="Action: Create a Rebel token.",
        ),
        _card("SOR", "003", "Administrator's Tower", "Base", aspects=["Vigilance"]),
        _card("SOR", "007", "Han Solo", "Leader", subtitle="Unowned Pilot", aspects=["Cunning"]),
        _card("SOR", "008", "Outer Rim Post", "Base", aspects=["Cunning"]),
        _card(
            "SOR", "004", "Jedi Guardian", "Unit", aspects=["Vigilance", "Heroism"],
            traits=["JEDI"], front_text="When Played: Restore 2 damage from a base.",
            keywords=["Sentinel"], cost="2", arenas=["Ground"],
        ),
        _card(
            "SOR", "005", "Force Recaller", "Event", aspects=["Heroism"],
            front_text="Return a friendly non-leader unit to its owner's hand.",
        ),
        _card("SOR", "006", "Outsider", "Unit", aspects=["Aggression"], cost="3"),
        _card(
            "ALT", "104", "Jedi Guardian", "Unit", aspects=["Vigilance", "Heroism"],
            traits=["JEDI"], front_text="When Played: Restore 2 damage from a base.",
            keywords=["Sentinel"], cost="2", arenas=["Ground"],
        ),
        _card(
            "SOR", "009", "Luke Skywalker", "Leader", subtitle="Jedi Knight",
            aspects=["Vigilance", "Heroism"], traits=["JEDI"],
        ),
        _card(
            "SOR", "010", "Reprint Leader", "Leader", subtitle="Proven Pilot",
            aspects=["Cunning"], traits=["PILOT"],
        ),
        _card(
            "ALT", "110", "Reprint Leader", "Leader", subtitle="Proven Pilot",
            aspects=["Cunning"], traits=["PILOT"],
        ),
        _card("SOR", "011", "Practice Token", "Token", aspects=["Vigilance"]),
        _card(
            "SOR",
            "012",
            "Expanded Squadron",
            "Unit",
            aspects=["Vigilance", "Heroism"],
            front_text="A deck can have up to 6 copies of this card.",
            cost="2",
        ),
        _card("JTLOP", "004", "Alias Guardian", "Unit", aspects=["Vigilance"]),
        _card("TSOR", "T04", "Alias Token", "Token", aspects=["Vigilance"]),
    ]
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(cards), encoding="utf-8")
    collection_path = tmp_path / "collection.json"
    collection_path.write_text(
        json.dumps({
            "entries": [
                {"set_code": "SOR", "card_number": "001", "count": 1, "foil_count": 0},
                {"set_code": "SOR", "card_number": "002", "count": 1, "foil_count": 0},
                {"set_code": "SOR", "card_number": "003", "count": 1, "foil_count": 0},
                {"set_code": "ALT", "card_number": "104", "count": 3, "foil_count": 2},
                {"set_code": "SOR", "card_number": "012", "count": 6, "foil_count": 0},
            ]
        }),
        encoding="utf-8",
    )
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(
        "swu_mcp.card_service.settings",
        Settings(card_catalog_path=str(catalog_path), cache_dir=cache_dir),
    )
    card_service = CardService()
    collection_service = CollectionService(collection_path)
    deck_service = DeckService(card_service, collection_service=collection_service)
    return {
        "service": AIBrewService(
            card_service,
            collection_service,
            deck_service,
            BrewSessionStore(tmp_path / "brews"),
        ),
        "deck_service": deck_service,
        "collection_path": collection_path,
        "store_path": tmp_path / "brews",
        "catalog_path": catalog_path,
        "cache_dir": cache_dir,
    }


def _start(service: AIBrewService, **overrides: object) -> dict[str, object]:
    request = {
        "format_name": "premier",
        "leader_names": ["Luke Skywalker - Faithful Friend"],
        "base_name": "Administrator's Tower",
        "theme": "midrange Force deck",
        "only_owned": False,
    }
    request.update(overrides)
    return service.start_brew(**request)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("format_name", "leader_names", "expected_ids"),
    [
        ("Premier", ["Luke Skywalker - Faithful Friend"], ["SOR/001"]),
        (
            "Twin Suns",
            ["Luke Skywalker - Faithful Friend", "Leia Organa - Rebel Ally"],
            ["SOR/001", "SOR/002"],
        ),
    ],
)
def test_start_brew_resolves_required_leaders_and_base(
    brew_components: dict[str, object],
    format_name: str,
    leader_names: list[str],
    expected_ids: list[str],
) -> None:
    service = brew_components["service"]

    result = _start(service, format_name=format_name, leader_names=leader_names)

    assert result["status"] == "ok"
    assert result["format_name"] == ("premier" if format_name == "Premier" else "twin_suns")
    assert [card["lookup_id"] for card in result["leaders"]] == expected_ids
    assert result["base"]["lookup_id"] == "SOR/003"


@pytest.mark.parametrize(
    ("leaders", "base_name", "message"),
    [
        (["Missing Leader"], "Administrator's Tower", "No card matched"),
        (["Jedi Guardian"], "Administrator's Tower", "Leader"),
        (["Luke Skywalker - Faithful Friend"], "Jedi Guardian", "Base"),
    ],
)
def test_start_brew_returns_structured_resolution_failures(
    brew_components: dict[str, object],
    leaders: list[str],
    base_name: str,
    message: str,
) -> None:
    service = brew_components["service"]

    result = _start(service, leader_names=leaders, base_name=base_name)

    assert result["status"] == "fail"
    assert message in result["error"]["message"]
    assert result["recovery_action"]


def test_start_brew_captures_owned_collection_snapshot_and_empty_revision(
    brew_components: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    service = brew_components["service"]
    deck_service = brew_components["deck_service"]
    collection_path = brew_components["collection_path"]
    monkeypatch.setattr(deck_service, "generate_deck", lambda **kwargs: pytest.fail("must not generate"))

    result = _start(service, only_owned=True)

    assert result["status"] == "ok"
    assert result["revision"] == 0
    assert result["collection_snapshot"] == {
        "path": str(collection_path),
        "sha256": hashlib.sha256(collection_path.read_bytes()).hexdigest(),
    }
    stored = BrewSessionStore(brew_components["store_path"]).load(result["session_id"])
    assert stored.revisions[0].main_deck == []
    assert stored.revisions[0].sideboard == []


def test_owned_start_uses_only_the_entries_parsed_from_the_hashed_payload(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    collection_path = brew_components["collection_path"]
    service.collection_service._load_from_disk()
    collection_path.write_text(
        json.dumps(
            {
                "entries": [
                    {"set_code": "SOR", "card_number": "007", "count": 1, "foil_count": 0},
                    {"set_code": "SOR", "card_number": "008", "count": 1, "foil_count": 0},
                ]
            }
        ),
        encoding="utf-8",
    )

    replacement = _start(
        service,
        leader_names=["Han Solo - Unowned Pilot"],
        base_name="Outer Rim Post",
        only_owned=True,
    )
    stale_original = _start(service, only_owned=True)

    assert replacement["status"] == "ok"
    assert replacement["leaders"][0]["lookup_id"] == "SOR/007"
    assert replacement["base"]["lookup_id"] == "SOR/008"
    assert replacement["collection_snapshot"]["sha256"] == hashlib.sha256(
        collection_path.read_bytes()
    ).hexdigest()
    context = service.get_context(
        session_id=replacement["session_id"],
        intent="candidates",
        limit=100,
    )
    assert {item["printing_id"] for item in context["cards"]} == {"SOR/007", "SOR/008"}
    assert stale_original["status"] == "fail"
    assert "not in the configured collection" in stale_original["error"]["message"]


def test_all_five_service_methods_use_the_stable_public_envelope(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service)
    context = service.get_context(
        session_id=started["session_id"],
        intent="session-summary",
    )
    decision = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        thesis="Use a stable public envelope.",
        rationale="Exercise the write envelope.",
    )
    evaluation = service.evaluate_brew(session_id=started["session_id"])
    finalization = service.finalize_brew(
        session_id=started["session_id"],
        expected_revision=1,
    )

    for result, expected_status in (
        (started, "ok"),
        (context, "ok"),
        (decision, "ok"),
        (evaluation, "ok"),
        (finalization, "fail"),
    ):
        assert result["status"] == expected_status
        assert set(("session_id", "revision", "stage", "diagnostics", "next_steps")) <= set(result)
        assert isinstance(result["diagnostics"], list)
        assert isinstance(result["next_steps"], list)

    assert started["stage"] == "planning"
    assert started["format_constraints"] == {
        "leaders": 1,
        "bases": 1,
        "main_deck_minimum": 50,
        "sideboard_maximum": 10,
        "default_copy_limit": 3,
    }
    assert started["next_steps"]


def test_start_brew_captures_collection_provenance_when_not_ownership_restricted(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    collection_path = brew_components["collection_path"]

    result = _start(
        service,
        leader_names=["Han Solo - Unowned Pilot"],
        base_name="Outer Rim Post",
        only_owned=False,
    )

    assert result["status"] == "ok"
    assert result["collection_snapshot"] == {
        "path": str(collection_path),
        "sha256": hashlib.sha256(collection_path.read_bytes()).hexdigest(),
    }
    stored = BrewSessionStore(brew_components["store_path"]).load(result["session_id"])
    assert stored.only_owned is False
    assert stored.collection_path == str(collection_path)
    assert stored.collection_snapshot_hash == result["collection_snapshot"]["sha256"]


def test_start_brew_captures_absent_collection_sentinel_without_ownership_enforcement(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    collection_path = brew_components["collection_path"]
    collection_path.unlink()

    result = _start(service, only_owned=False)

    assert result["status"] == "ok"
    assert result["collection_snapshot"] == {
        "path": str(collection_path),
        "sha256": _collection_hash(collection_path),
    }
    assert result["collection_snapshot"]["sha256"].startswith("absent:v1:")


def test_unowned_brew_blocks_stale_collection_without_a_refresh(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    collection_path = brew_components["collection_path"]
    started = _start(service, only_owned=False)
    before = _session_bytes(brew_components, started["session_id"])
    collection_path.write_text(json.dumps({"entries": [], "changed": True}), encoding="utf-8")

    result = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=[{"printing_id": "SOR/004", "quantity": 1}],
        rationale="This must fail until collection refresh is explicit.",
    )

    assert result["status"] == "fail"
    assert result["collection"]["old_hash"] == started["collection_snapshot"]["sha256"]
    assert result["collection"]["new_hash"] == _collection_hash(collection_path)
    assert _session_bytes(brew_components, started["session_id"]) == before


def test_context_returns_factual_candidate_evidence_and_inclusion_state(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service, only_owned=True)

    result = service.get_context(session_id=started["session_id"], intent="candidates")
    guardian = next(item for item in result["cards"] if item["printing_id"] == "SOR/004")

    assert result["status"] == "ok"
    assert guardian["card"]["front_text"] == "When Played: Restore 2 damage from a base."
    assert guardian["ownership"] == {"owned": True, "count": 3, "foil_count": 2}
    assert "defense" in guardian["inferred_roles"]
    assert "replay_engine" in guardian["package_tags"]
    assert guardian["interactions"]["provides"]
    assert guardian["inclusion"] == {"state": "not_in_revision", "quantity": 0}


def test_context_cursor_is_stable_and_rejects_mismatched_or_invalid_values(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service)

    first = service.get_context(session_id=started["session_id"], intent="candidates", limit=2)
    second = service.get_context(
        session_id=started["session_id"], intent="candidates", cursor=first["next_cursor"], limit=2
    )
    mismatched = service.get_context(
        session_id=started["session_id"], intent="candidates", filters={"type": "Unit"}, cursor=first["next_cursor"]
    )
    invalid = service.get_context(session_id=started["session_id"], intent="candidates", cursor="not-a-cursor")

    assert set(item["printing_id"] for item in first["cards"]).isdisjoint(
        {item["printing_id"] for item in second["cards"]}
    )
    assert mismatched["status"] == "fail"
    assert invalid["status"] == "fail"


def test_context_summary_and_history_survive_a_fresh_service_instance(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service)
    fresh = AIBrewService(
        service.card_service,
        service.collection_service,
        service.deck_service,
        BrewSessionStore(brew_components["store_path"]),
    )

    summary = fresh.get_context(session_id=started["session_id"], intent="session-summary")
    history = fresh.get_context(session_id=started["session_id"], intent="revision-history")

    assert summary["status"] == "ok"
    assert summary["session"]["current_revision"] == 0
    assert history["status"] == "ok"
    assert [revision["revision"] for revision in history["revisions"]] == [0]


def test_context_marks_changed_collection_stale_but_remains_read_only(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    collection_path = brew_components["collection_path"]
    started = _start(service, only_owned=True)
    collection_path.write_text(json.dumps({"entries": []}), encoding="utf-8")

    result = service.get_context(session_id=started["session_id"], intent="candidates")

    assert result["status"] == "ok"
    assert result["collection"]["stale"] is True
    assert result["cards"] == []
    assert result["diagnostics"][0]["code"] == "collection_snapshot_stale"


def test_context_aggregates_alternate_printing_ownership_by_canonical_card(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service, only_owned=True)

    result = service.get_context(session_id=started["session_id"], intent="candidates")
    displayed_printing = next(item for item in result["cards"] if item["printing_id"] == "SOR/004")

    assert displayed_printing["card"]["lookup_id"] == "SOR/004"
    assert displayed_printing["ownership"] == {"owned": True, "count": 3, "foil_count": 2}


def test_start_brew_rejects_ambiguous_leader_name_with_candidates(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]

    result = _start(service, leader_names=["Luke Skywalker"])

    assert result["status"] == "fail"
    assert "Ambiguous leader" in result["error"]["message"]
    assert {candidate["lookup_id"] for candidate in result["error"]["candidates"]} == {
        "SOR/001", "SOR/009"
    }
    assert "SET/NNN" in result["recovery_action"]


def test_start_brew_resolves_explicit_printing_ids_exactly(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]

    result = _start(service, leader_names=["SOR/009"], base_name="SOR/003")

    assert result["status"] == "ok"
    assert [leader["lookup_id"] for leader in result["leaders"]] == ["SOR/009"]
    assert result["base"]["lookup_id"] == "SOR/003"


def test_start_brew_rejects_bare_name_for_canonical_equivalent_reprints(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]

    result = _start(service, leader_names=["Reprint Leader - Proven Pilot"])

    assert result["status"] == "fail"
    assert {candidate["lookup_id"] for candidate in result["error"]["candidates"]} == {
        "SOR/010", "ALT/110"
    }
    assert "SET/NNN" in result["recovery_action"]


def test_start_brew_resolves_explicit_id_for_canonical_equivalent_reprint(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]

    result = _start(service, leader_names=["ALT/110"])

    assert result["status"] == "ok"
    assert [leader["lookup_id"] for leader in result["leaders"]] == ["ALT/110"]


def test_start_brew_returns_runtime_resolution_failures_in_public_envelope(
    brew_components: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    service = brew_components["service"]
    deck_service = brew_components["deck_service"]

    def unavailable(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("catalog backend is unavailable")

    monkeypatch.setattr(deck_service, "resolve_deck", unavailable)

    result = _start(service)

    assert result["status"] == "fail"
    assert result["session_id"] is None
    assert result["revision"] is None
    assert result["stage"] is None
    assert result["error"] == {"message": "catalog backend is unavailable"}
    assert result["diagnostics"] == [
        {
            "severity": "error",
            "code": "RuntimeError",
            "message": "catalog backend is unavailable",
        }
    ]
    assert result["next_steps"] == [
        "Correct the setup details and start a new brew session."
    ]
    assert result["recovery_action"] == result["next_steps"][0]


def test_missing_collection_hash_is_fixed_across_different_paths(tmp_path: Path) -> None:
    first = _collection_hash(tmp_path / "first" / "collection.json")
    second = _collection_hash(tmp_path / "second" / "collection.json")

    assert first == second
    assert first.startswith("absent:v1:")


def test_decision_ids_accept_supported_long_set_codes() -> None:
    assert AIBrewService._decision_printing_id(
        {"printing_id": "SOROPJ/001"}
    ) == "SOROPJ/001"


def test_fixture_constructs_card_service_with_only_temporary_cache(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    cache_dir = brew_components["cache_dir"]
    catalog_path = brew_components["catalog_path"]

    service.card_service._write_cache("isolation.json", {"temporary": True})

    assert service.card_service.cache_dir == cache_dir
    assert service.card_service.catalog.catalog_path == catalog_path
    assert (cache_dir / "isolation.json").exists()


def _session_bytes(components: dict[str, object], session_id: str) -> bytes:
    return (components["store_path"] / f"{session_id}.json").read_bytes()


def test_record_decisions_aggregates_canonical_quantities_and_keeps_selected_printing(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service, only_owned=True)

    added = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=[
            {"printing_id": "ALT/104", "quantity": 1},
            {"printing_id": "SOR/004", "quantity": 2},
        ],
        rationale="Add the three owned Guardian copies.",
    )

    assert added["status"] == "ok"
    assert added["revision"] == 1
    stored = BrewSessionStore(brew_components["store_path"]).load(started["session_id"])
    assert len(stored.revisions) == 2
    assert len(stored.decisions) == 1
    assert len(stored.revisions[1].main_deck) == 1
    assert stored.revisions[1].main_deck[0]["lookup_id"] == "ALT/104"
    assert stored.revisions[1].main_deck[0]["quantity"] == 3

    cut = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=1,
        cuts=[{"printing_id": "SOR/004", "quantity": 1}],
        rationale="Trim one Guardian from the curve.",
    )

    assert cut["status"] == "ok"
    stored = BrewSessionStore(brew_components["store_path"]).load(started["session_id"])
    assert len(stored.revisions) == 3
    assert len(stored.decisions) == 2
    assert stored.revisions[2].main_deck[0]["lookup_id"] == "ALT/104"
    assert stored.revisions[2].main_deck[0]["quantity"] == 2


def test_record_decisions_resolves_the_requested_exact_printing_id(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service)

    result = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=[{"printing_id": "SOR/004", "quantity": 1}],
        rationale="Choose this exact printing.",
    )

    assert result["status"] == "ok"
    revision = BrewSessionStore(brew_components["store_path"]).load(started["session_id"]).revisions[1]
    assert revision.main_deck[0]["lookup_id"] == "SOR/004"


@pytest.mark.parametrize(
    ("only_owned", "change", "message"),
    [
        (True, {"printing_id": "ALT/104", "quantity": 3}, "ownership"),
        (False, {"printing_id": "SOR/004", "quantity": 4}, "copy"),
        (False, {"printing_id": "SOR/004", "quantity": -1}, "nonnegative"),
        (False, {"printing_id": "SOR/001", "quantity": 1}, "unit, event, or upgrade"),
        (False, {"printing_id": "ZZZ/999", "quantity": 1}, "could not resolve"),
        (False, {"printing_id": "SOR/006", "quantity": 1}, "off-aspect"),
    ],
)
def test_record_decisions_rejects_invalid_deck_changes_without_writing(
    brew_components: dict[str, object],
    only_owned: bool,
    change: dict[str, object],
    message: str,
) -> None:
    service = brew_components["service"]
    collection_path = brew_components["collection_path"]
    if only_owned:
        collection_path.write_text(
            json.dumps(
                {
                    "entries": [
                        {"set_code": "SOR", "card_number": "001", "count": 1, "foil_count": 0},
                        {"set_code": "SOR", "card_number": "003", "count": 1, "foil_count": 0},
                        {"set_code": "ALT", "card_number": "104", "count": 2, "foil_count": 0},
                    ]
                }
            ),
            encoding="utf-8",
        )
    started = _start(service, only_owned=only_owned)
    before = _session_bytes(brew_components, started["session_id"])

    result = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=[change],
        rationale="Try an invalid change.",
    )

    assert result["status"] == "fail"
    assert message in result["error"]["message"].lower()
    assert _session_bytes(brew_components, started["session_id"]) == before


def test_record_decisions_enforces_twin_suns_singleton_by_canonical_identity(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(
        service,
        format_name="twin_suns",
        leader_names=["Luke Skywalker - Faithful Friend", "Leia Organa - Rebel Ally"],
    )
    before = _session_bytes(brew_components, started["session_id"])

    result = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=[
            {"printing_id": "SOR/004", "quantity": 1},
            {"printing_id": "ALT/104", "quantity": 1},
        ],
        rationale="This should be rejected as duplicate canonical copies.",
    )

    assert result["status"] == "fail"
    assert "copy limit is 1" in result["error"]["message"]
    assert _session_bytes(brew_components, started["session_id"]) == before


def test_record_decisions_rejects_stale_revision_and_missing_substantive_rationale_without_writing(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service)
    first = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=[{"printing_id": "SOR/004", "quantity": 1}],
        rationale="Start the curve.",
    )
    assert first["status"] == "ok"
    before = _session_bytes(brew_components, started["session_id"])

    stale = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=[{"printing_id": "SOR/005", "quantity": 1}],
        rationale="This must not overwrite the current draft.",
    )
    missing_rationale = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=1,
        additions=[{"printing_id": "SOR/005", "quantity": 1}],
    )

    assert stale["status"] == "fail"
    assert "expected revision" in stale["error"]["message"]
    assert missing_rationale["status"] == "fail"
    assert "rationale" in missing_rationale["error"]["message"]
    assert _session_bytes(brew_components, started["session_id"]) == before


def test_record_decisions_keeps_reservations_and_rejections_out_of_the_deck(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service)

    result = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        reservations=[{"printing_id": "SOR/004", "quantity": 1, "reason": "Keep in reserve."}],
        rejected_cards=[{"printing_id": "SOR/006", "reason": "Outside the deck aspects."}],
        rationale="Track candidates separately from the deck.",
    )

    assert result["status"] == "ok"
    revision = BrewSessionStore(brew_components["store_path"]).load(started["session_id"]).revisions[1]
    assert revision.main_deck == []
    assert revision.reservations[0]["lookup_id"] == "SOR/004"
    assert revision.rejected_cards[0]["lookup_id"] == "SOR/006"


def test_record_decisions_persists_thesis_packages_and_role_targets(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service)

    result = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        thesis="Force recursion with a resilient early curve.",
        packages=[{"name": "force_engine", "target": 8}],
        role_targets={"defense": 7, "replay": 5},
        rationale="Set the explicit deck plan.",
    )

    assert result["status"] == "ok"
    revision = BrewSessionStore(brew_components["store_path"]).load(started["session_id"]).revisions[1]
    assert revision.thesis == "Force recursion with a resilient early curve."
    assert revision.packages == [{"name": "force_engine", "target": 8}]
    assert revision.role_targets == {"defense": 7, "replay": 5}


def test_record_decisions_restores_as_a_new_child_revision_without_erasing_history(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service)
    assert service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=[{"printing_id": "SOR/004", "quantity": 1}],
        rationale="First version.",
    )["status"] == "ok"
    assert service.record_decisions(
        session_id=started["session_id"],
        expected_revision=1,
        additions=[{"printing_id": "SOR/005", "quantity": 1}],
        rationale="Second version.",
    )["status"] == "ok"

    restored = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=2,
        restore_revision=0,
        rationale="Return to the empty starting point.",
    )

    assert restored["status"] == "ok"
    stored = BrewSessionStore(brew_components["store_path"]).load(started["session_id"])
    assert [revision.revision for revision in stored.revisions] == [0, 1, 2, 3]
    assert stored.revisions[3].parent_revision == 0
    assert stored.revisions[2].main_deck[0]["lookup_id"] == "SOR/004"
    assert stored.revisions[3].main_deck == []


def test_restore_validates_advisory_report_against_the_selected_parent_revision(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service)
    assert service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=[{"printing_id": "SOR/004", "quantity": 1}],
        rationale="Advance to revision one.",
    )["status"] == "ok"
    _append_report(
        service,
        session_id=started["session_id"],
        report_id="report-for-restored-parent",
        revision=0,
    )

    restored = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=1,
        restore_revision=0,
        advisory_report_id="report-for-restored-parent",
        rationale="Restore revision zero using evidence bound to revision zero.",
    )

    assert restored["status"] == "ok"
    stored = service.store.load(started["session_id"])
    assert stored.revisions[2].parent_revision == 0
    assert stored.decisions[-1].accepted_stale_evidence is False


def test_record_decisions_after_finalization_preserves_receipts_and_returns_to_revising(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service)
    stored = service.store.load(started["session_id"])
    stored.stage = "finalized"
    receipt = {
        "receipt_id": "receipt-1",
        "finalized_at": "2026-08-15T12:05:00Z",
        "revision": 0,
        "finalized_revision_sha256": canonical_revision_hash(stored.revisions[0]),
        "collection": {
            "tracked": True,
            "path": stored.collection_path,
            "snapshot_hash": stored.collection_snapshot_hash,
            "current_hash": stored.collection_snapshot_hash,
            "stale": False,
        },
        "validation": {},
        "analysis": {},
        "export_hashes": {
            "plain_text_sha256": "a" * 64,
            "holoscan_sha256": "b" * 64,
        },
        "current_advisory_report": None,
        "stale_advisory_reports": [],
        "decision_history": [],
    }
    stored.finalization_receipts.append(receipt)
    service.store.save(stored)

    result = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=[{"printing_id": "SOR/004", "quantity": 1}],
        rationale="Reopen the final deck for a correction.",
    )

    assert result["status"] == "ok"
    reloaded = service.store.load(started["session_id"])
    assert reloaded.stage == "revising"
    assert reloaded.finalization_receipts == [receipt]


def test_record_decisions_blocks_stale_collection_without_a_refresh(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    collection_path = brew_components["collection_path"]
    started = _start(service, only_owned=True)
    before = _session_bytes(brew_components, started["session_id"])
    collection_path.write_text(json.dumps({"entries": []}), encoding="utf-8")

    result = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=[{"printing_id": "SOR/004", "quantity": 1}],
        rationale="This must fail until collection refresh is explicit.",
    )

    assert result["status"] == "fail"
    assert result["collection"]["old_hash"] == started["collection_snapshot"]["sha256"]
    assert result["collection"]["new_hash"] == _collection_hash(collection_path)
    assert _session_bytes(brew_components, started["session_id"]) == before


def test_unowned_brew_refreshes_stale_collection_and_records_history(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    collection_path = brew_components["collection_path"]
    started = _start(service, only_owned=False)
    old_hash = started["collection_snapshot"]["sha256"]
    collection_path.write_text(json.dumps({"entries": [], "changed": True}), encoding="utf-8")
    new_hash = _collection_hash(collection_path)

    refreshed = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=[{"printing_id": "SOR/004", "quantity": 1}],
        rationale="Rebind the unrestricted brew to the current collection snapshot.",
        refresh_collection=True,
    )

    assert refreshed["status"] == "ok"
    stored = BrewSessionStore(brew_components["store_path"]).load(started["session_id"])
    assert stored.collection_snapshot_hash == new_hash
    assert stored.collection_refreshes == [
        {
            "old_hash": old_hash,
            "new_hash": new_hash,
            "revision": 1,
            "created_at": stored.revisions[1].created_at,
        }
    ]


def test_record_decisions_refreshes_collection_only_after_conflicts_are_resolved(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    collection_path = brew_components["collection_path"]
    started = _start(service, only_owned=True)
    initial = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=[{"printing_id": "ALT/104", "quantity": 3}],
        rationale="Select all three initially owned copies.",
    )
    assert initial["status"] == "ok"
    old_hash = started["collection_snapshot"]["sha256"]
    collection_path.write_text(
        json.dumps(
            {
                "entries": [
                    {"set_code": "SOR", "card_number": "001", "count": 1, "foil_count": 0},
                    {"set_code": "SOR", "card_number": "003", "count": 1, "foil_count": 0},
                    {"set_code": "ALT", "card_number": "104", "count": 2, "foil_count": 0},
                ]
            }
        ),
        encoding="utf-8",
    )
    new_hash = _collection_hash(collection_path)
    before = _session_bytes(brew_components, started["session_id"])

    conflicted = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=1,
        rationale="Attempt to retain the stale three-copy list.",
        refresh_collection=True,
    )

    assert conflicted["status"] == "fail"
    assert conflicted["collection"]["conflicts"] == [
        {"printing_id": "ALT/104", "requested": 3, "owned": 2}
    ]
    assert _session_bytes(brew_components, started["session_id"]) == before

    refreshed = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=1,
        cuts=[{"printing_id": "ALT/104", "quantity": 1}],
        rationale="Keep the two copies still owned.",
        refresh_collection=True,
    )

    assert refreshed["status"] == "ok"
    stored = BrewSessionStore(brew_components["store_path"]).load(started["session_id"])
    assert stored.collection_snapshot_hash == new_hash
    assert len(stored.collection_refreshes) == 1
    assert stored.collection_refreshes[0]["old_hash"] == old_hash
    assert stored.collection_refreshes[0]["new_hash"] == new_hash
    assert stored.collection_refreshes[0]["revision"] == 2


def test_collection_refresh_revalidates_immutable_leader_and_base_ownership(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    collection_path = brew_components["collection_path"]
    started = _start(service, only_owned=True)
    before = _session_bytes(brew_components, started["session_id"])
    collection_path.write_text(
        json.dumps(
            {
                "entries": [
                    {"set_code": "ALT", "card_number": "104", "count": 3, "foil_count": 0}
                ]
            }
        ),
        encoding="utf-8",
    )

    result = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        refresh_collection=True,
        rationale="Attempt to refresh after losing the immutable setup cards.",
    )

    assert result["status"] == "fail"
    assert result["collection"]["conflicts"] == [
        {"printing_id": "SOR/001", "requested": 1, "owned": 0},
        {"printing_id": "SOR/003", "requested": 1, "owned": 0},
    ]
    assert _session_bytes(brew_components, started["session_id"]) == before


@pytest.mark.parametrize(
    ("format_name", "leader_names", "quantity"),
    [
        ("premier", ["Luke Skywalker - Faithful Friend"], 4),
        (
            "twin_suns",
            ["Luke Skywalker - Faithful Friend", "Leia Organa - Rebel Ally"],
            2,
        ),
    ],
)
def test_ai_brew_uses_the_deck_validator_card_text_copy_limit_override(
    brew_components: dict[str, object],
    format_name: str,
    leader_names: list[str],
    quantity: int,
) -> None:
    service = brew_components["service"]
    started = _start(service, format_name=format_name, leader_names=leader_names)

    result = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=[{"printing_id": "SOR/012", "quantity": quantity}],
        rationale="Use the copy limit stated on the card.",
    )

    assert result["status"] == "ok"
    stored = service.store.load(started["session_id"])
    assert stored.revisions[1].main_deck[0]["quantity"] == quantity


def test_start_rejects_twin_suns_leaders_without_shared_alignment(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]

    result = _start(
        service,
        format_name="twin_suns",
        leader_names=["Luke Skywalker - Faithful Friend", "Han Solo - Unowned Pilot"],
    )

    assert result["status"] == "fail"
    assert "share Heroism or Villainy" in result["error"]["message"]


def test_decision_record_persists_every_submitted_decision_group_delta(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service)
    assert service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=[{"printing_id": "SOR/004", "quantity": 1}],
        rationale="Seed a card that the next decision can cut.",
    )["status"] == "ok"

    result = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=1,
        thesis="Shift to a recursion plan.",
        packages=[{"name": "replay_engine", "target": 6}],
        role_targets={"defense": 7},
        additions=[{"printing_id": "SOR/005", "quantity": 1}],
        cuts=[{"printing_id": "SOR/004", "quantity": 1}],
        reservations=[{"printing_id": "SOR/004", "quantity": 1}],
        rejected_cards=[{"printing_id": "SOR/006", "quantity": 1}],
        rationale="Persist every caller-authored decision group.",
    )

    assert result["status"] == "ok"
    decision = service.store.load(started["session_id"]).decisions[-1]
    assert decision.thesis == "Shift to a recursion plan."
    assert decision.packages == [{"name": "replay_engine", "target": 6}]
    assert decision.role_targets == {"defense": 7}
    assert [entry["lookup_id"] for entry in decision.additions] == ["SOR/005"]
    assert [entry["lookup_id"] for entry in decision.cuts] == ["SOR/004"]
    assert [entry["lookup_id"] for entry in decision.reservations] == ["SOR/004"]
    assert [entry["lookup_id"] for entry in decision.rejected_cards] == ["SOR/006"]


@pytest.mark.parametrize("printing_id", ["SOR/4", "sor/004", "JTLP/004", "TOKENS/004"])
def test_record_decisions_rejects_noncanonical_or_alias_printings_without_writing(
    brew_components: dict[str, object], printing_id: str
) -> None:
    service = brew_components["service"]
    started = _start(service)
    before = _session_bytes(brew_components, started["session_id"])

    result = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=[{"printing_id": printing_id, "quantity": 1}],
        rationale="Attempt a noncanonical printing identity.",
    )

    assert result["status"] == "fail"
    assert _session_bytes(brew_components, started["session_id"]) == before


def test_record_decisions_rejects_token_cards_without_writing(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service)
    before = _session_bytes(brew_components, started["session_id"])

    result = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=[{"printing_id": "SOR/011", "quantity": 1}],
        rationale="Attempt to add a Token card.",
    )

    assert result["status"] == "fail"
    assert "Unit, Event, or Upgrade" in result["error"]["message"]
    assert _session_bytes(brew_components, started["session_id"]) == before


def test_record_decisions_rejects_collection_change_after_refresh_validation_without_writing(
    brew_components: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    service = brew_components["service"]
    collection_path = brew_components["collection_path"]
    started = _start(service, only_owned=True)
    refreshed_payload = {
        "refresh_marker": "validated",
        "entries": [
            {"set_code": "SOR", "card_number": "001", "count": 1, "foil_count": 0},
            {"set_code": "SOR", "card_number": "003", "count": 1, "foil_count": 0},
            {"set_code": "ALT", "card_number": "104", "count": 3, "foil_count": 2},
        ],
    }
    collection_path.write_text(json.dumps(refreshed_payload), encoding="utf-8")
    before = _session_bytes(brew_components, started["session_id"])
    validate = service._validate_prospective_revision

    def validate_then_change_collection(
        *args: object, **kwargs: object
    ) -> None:
        validate(*args, **kwargs)  # type: ignore[arg-type]
        collection_path.write_text(
            json.dumps({**refreshed_payload, "refresh_marker": "changed-after-validation"}),
            encoding="utf-8",
        )

    monkeypatch.setattr(service, "_validate_prospective_revision", validate_then_change_collection)

    result = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=[{"printing_id": "ALT/104", "quantity": 1}],
        rationale="Refresh against the current collection.",
        refresh_collection=True,
    )

    assert result["status"] == "fail"
    assert "changed during decision validation" in result["error"]["message"]
    assert _session_bytes(brew_components, started["session_id"]) == before


def _append_report(
    service: AIBrewService,
    *,
    session_id: str,
    report_id: str,
    revision: int,
) -> None:
    session = service.store.load(session_id)
    session.reports.append(
        BrewReport(
            report_id=report_id,
            revision=revision,
            created_at="2026-08-15T12:00:00Z",
            inputs={},
            result={},
        )
    )
    service.store.save(session)


def test_record_decisions_rejects_unknown_advisory_report_without_writing(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service)
    before = _session_bytes(brew_components, started["session_id"])

    result = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        thesis="A decision cannot cite an unknown report.",
        rationale="Attempt unknown report provenance.",
        advisory_report_id="missing-report",
        accept_stale_evidence=True,
    )

    assert result["status"] == "fail"
    assert "Unknown advisory report ID" in result["error"]["message"]
    assert _session_bytes(brew_components, started["session_id"]) == before


def test_record_decisions_rejects_advisory_report_from_another_revision_without_writing(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service)
    first = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=[{"printing_id": "SOR/004", "quantity": 1}],
        rationale="Create revision one before recording its older report.",
    )
    assert first["status"] == "ok"
    _append_report(
        service,
        session_id=started["session_id"],
        report_id="report-for-revision-zero",
        revision=0,
    )
    before = _session_bytes(brew_components, started["session_id"])

    result = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=1,
        additions=[{"printing_id": "SOR/005", "quantity": 1}],
        rationale="Attempt to cite an older report.",
        advisory_report_id="report-for-revision-zero",
    )

    assert result["status"] == "fail"
    assert "bound to revision 0" in result["error"]["message"]
    assert _session_bytes(brew_components, started["session_id"]) == before


def test_record_decisions_accepts_current_report_and_records_default_stale_evidence_flag(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service)
    _append_report(
        service,
        session_id=started["session_id"],
        report_id="report-for-current-revision",
        revision=0,
    )

    result = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        thesis="Use current-revision evaluation evidence.",
        rationale="Record a decision with its current advisory evidence.",
        advisory_report_id="report-for-current-revision",
    )

    assert result["status"] == "ok"
    stored = service.store.load(started["session_id"])
    assert stored.decisions[-1].advisory_report_id == "report-for-current-revision"
    assert stored.decisions[-1].accepted_stale_evidence is False


def test_record_decisions_allows_explicit_stale_report_and_persists_acceptance(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service)
    first = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=[{"printing_id": "SOR/004", "quantity": 1}],
        rationale="Create revision one before using revision zero evidence.",
    )
    assert first["status"] == "ok"
    _append_report(
        service,
        session_id=started["session_id"],
        report_id="report-for-revision-zero",
        revision=0,
    )

    result = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=1,
        additions=[{"printing_id": "SOR/005", "quantity": 1}],
        rationale="Explicitly retain a still-relevant older report.",
        advisory_report_id="report-for-revision-zero",
        accept_stale_evidence=True,
    )

    assert result["status"] == "ok"
    stored = service.store.load(started["session_id"])
    assert stored.decisions[-1].accepted_stale_evidence is True
    assert stored.decisions[-1].advisory_report_id == "report-for-revision-zero"


def test_record_decisions_rejects_stale_acceptance_flag_without_stale_report(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service)
    _append_report(
        service,
        session_id=started["session_id"],
        report_id="report-for-current-revision",
        revision=0,
    )
    before = _session_bytes(brew_components, started["session_id"])

    result = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        thesis="Do not label current evidence as stale.",
        rationale="The acceptance flag requires an older referenced report.",
        advisory_report_id="report-for-current-revision",
        accept_stale_evidence=True,
    )

    assert result["status"] == "fail"
    assert "stale" in result["error"]["message"].lower()
    assert _session_bytes(brew_components, started["session_id"]) == before


def test_context_filters_use_computed_candidate_facts_and_ignore_schema_defaults(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service, only_owned=True)

    unfiltered = service.get_context(session_id=started["session_id"], intent="candidates")
    defaults = service.get_context(
        session_id=started["session_id"],
        intent="candidates",
        filters=BrewContextFilters().model_dump(mode="json"),
    )
    filtered = service.get_context(
        session_id=started["session_id"],
        intent="candidates",
        filters={
            "roles": ["defense", "early_unit"],
            "packages": ["force_engine"],
            "min_cost": 2,
            "max_cost": 2,
            "card_types": ["Unit"],
            "aspects": ["Heroism"],
            "traits": ["JEDI"],
            "keywords": ["Sentinel"],
            "text": "Restore",
            "minimum_owned": 3,
            "inclusion_state": "excluded",
        },
    )

    assert unfiltered["status"] == "ok"
    assert defaults["status"] == "ok"
    assert [item["printing_id"] for item in defaults["cards"]] == [
        item["printing_id"] for item in unfiltered["cards"]
    ]
    assert filtered["status"] == "ok"
    assert {item["printing_id"] for item in filtered["cards"]} == {"SOR/004", "ALT/104"}
    for item in filtered["cards"]:
        assert {"defense", "early_unit"}.issubset(item["inferred_roles"])
        assert "force_engine" in item["package_tags"]
        assert item["ownership"]["count"] >= 3
        assert item["inclusion"] == {"state": "not_in_revision", "quantity": 0}

    recorded = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=[{"printing_id": "SOR/004", "quantity": 1}],
        rationale="Record the selected Guardian before filtering included cards.",
    )
    included = service.get_context(
        session_id=started["session_id"],
        intent="candidates",
        filters={"inclusion_state": "included"},
    )

    assert recorded["status"] == "ok"
    assert [item["printing_id"] for item in included["cards"]] == ["SOR/004"]


def test_context_filters_reject_invalid_ranges_and_incompatible_cursors(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service)
    first = service.get_context(session_id=started["session_id"], intent="candidates", limit=1)

    invalid_range = service.get_context(
        session_id=started["session_id"],
        intent="candidates",
        filters={"min_cost": 4, "max_cost": 2},
    )
    invalid_value = service.get_context(
        session_id=started["session_id"],
        intent="candidates",
        filters={"minimum_owned": -1},
    )
    incompatible_cursor = service.get_context(
        session_id=started["session_id"],
        intent="candidates",
        filters={"card_types": ["Unit"]},
        cursor=first["next_cursor"],
    )

    assert invalid_range["status"] == "fail"
    assert "min_cost" in invalid_range["error"]["message"]
    assert invalid_value["status"] == "fail"
    assert "minimum_owned" in invalid_value["error"]["message"]
    assert incompatible_cursor["status"] == "fail"
    assert "cursor" in incompatible_cursor["error"]["message"].lower()


def test_context_summary_and_history_ignore_candidate_only_filters(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service)

    summary = service.get_context(
        session_id=started["session_id"],
        intent="session-summary",
        filters={"min_cost": 4, "max_cost": 2},
    )
    history = service.get_context(
        session_id=started["session_id"],
        intent="revision-history",
        filters={"unknown": "ignored"},
    )

    assert summary["status"] == "ok"
    assert history["status"] == "ok"


def test_context_filters_preserve_legacy_type_aspect_trait_and_query_aliases(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service)

    result = service.get_context(
        session_id=started["session_id"],
        intent="candidates",
        filters={"type": "Unit", "aspect": "Heroism", "trait": "JEDI", "query": "Restore"},
    )

    assert result["status"] == "ok"
    assert {item["printing_id"] for item in result["cards"]} == {"SOR/004", "ALT/104"}


def test_get_brew_context_wrapper_uses_real_service_filters(
    brew_components: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    service = brew_components["service"]
    monkeypatch.setattr(server, "ai_brew_service", service)
    started = _start(service, only_owned=True)

    result = server.swu_get_brew_context(
        session_id=started["session_id"],
        intent="candidates",
        filters=BrewContextFilters(
            roles=["defense"],
            card_types=["Unit"],
            keywords=["Sentinel"],
            text="Restore",
            minimum_owned=3,
        ),
    )

    assert result["status"] == "ok"
    assert {item["printing_id"] for item in result["cards"]} == {"SOR/004", "ALT/104"}


def test_get_brew_context_wrapper_preserves_legacy_filter_aliases(
    brew_components: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    service = brew_components["service"]
    monkeypatch.setattr(server, "ai_brew_service", service)
    started = _start(service)

    result = server.swu_get_brew_context(
        session_id=started["session_id"],
        intent="candidates",
        filters=BrewContextFilters(
            type="Unit",
            aspect="Heroism",
            trait="JEDI",
            query="Restore",
        ),
    )

    assert result["status"] == "ok"
    assert {item["printing_id"] for item in result["cards"]} == {"SOR/004", "ALT/104"}


def test_record_decisions_routes_and_cuts_sideboard_changes(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    started = _start(service)

    added = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=[
            {"printing_id": "SOR/004", "quantity": 1, "zone": "main_deck"},
            {"printing_id": "SOR/005", "quantity": 1, "zone": "sideboard"},
        ],
        rationale="Put the Guardian in the deck and Recaller in the sideboard.",
    )
    after_add = service.store.load(started["session_id"])
    cut = service.record_decisions(
        session_id=started["session_id"],
        expected_revision=1,
        cuts=[{"printing_id": "SOR/005", "quantity": 1, "zone": "sideboard"}],
        rationale="Remove the sideboard Recaller.",
    )
    after_cut = service.store.load(started["session_id"])

    assert added["status"] == "ok"
    assert [(card["lookup_id"], card["quantity"]) for card in after_add.revisions[1].main_deck] == [
        ("SOR/004", 1)
    ]
    assert [(card["lookup_id"], card["quantity"]) for card in after_add.revisions[1].sideboard] == [
        ("SOR/005", 1)
    ]
    assert cut["status"] == "ok"
    assert after_cut.revisions[2].main_deck[0]["lookup_id"] == "SOR/004"
    assert after_cut.revisions[2].sideboard == []


def test_record_decisions_fails_closed_for_sideboard_format_and_size_limits(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    premier = _start(service)
    premier_before = _session_bytes(brew_components, premier["session_id"])
    overflow = service.record_decisions(
        session_id=premier["session_id"],
        expected_revision=0,
        additions=[{"printing_id": "SOR/004", "quantity": 11, "zone": "sideboard"}],
        rationale="Attempt to exceed the Premier sideboard limit.",
    )
    twin_suns = _start(
        service,
        format_name="twin_suns",
        leader_names=["Luke Skywalker - Faithful Friend", "Leia Organa - Rebel Ally"],
    )
    twin_before = _session_bytes(brew_components, twin_suns["session_id"])
    twin_sideboard = service.record_decisions(
        session_id=twin_suns["session_id"],
        expected_revision=0,
        additions=[{"printing_id": "SOR/004", "quantity": 1, "zone": "sideboard"}],
        rationale="Twin Suns must not accept sideboard cards.",
    )

    assert overflow["status"] == "fail"
    assert "sideboard max" in overflow["error"]["message"].lower()
    assert _session_bytes(brew_components, premier["session_id"]) == premier_before
    assert twin_sideboard["status"] == "fail"
    assert "sideboard" in twin_sideboard["error"]["message"].lower()
    assert _session_bytes(brew_components, twin_suns["session_id"]) == twin_before


def test_record_decisions_combines_main_and_sideboard_copy_and_ownership_limits(
    brew_components: dict[str, object]
) -> None:
    service = brew_components["service"]
    copy_limited = _start(service)
    copy_before = _session_bytes(brew_components, copy_limited["session_id"])
    copy_result = service.record_decisions(
        session_id=copy_limited["session_id"],
        expected_revision=0,
        additions=[
            {"printing_id": "SOR/004", "quantity": 2, "zone": "main_deck"},
            {"printing_id": "ALT/104", "quantity": 2, "zone": "sideboard"},
        ],
        rationale="Attempt to exceed the combined Premier canonical copy limit.",
    )

    collection_path = brew_components["collection_path"]
    collection_path.write_text(
        json.dumps(
            {
                "entries": [
                    {"set_code": "SOR", "card_number": "001", "count": 1, "foil_count": 0},
                    {"set_code": "SOR", "card_number": "003", "count": 1, "foil_count": 0},
                    {"set_code": "ALT", "card_number": "104", "count": 2, "foil_count": 0},
                ]
            }
        ),
        encoding="utf-8",
    )
    ownership_limited = _start(service, only_owned=True)
    ownership_before = _session_bytes(brew_components, ownership_limited["session_id"])
    ownership_result = service.record_decisions(
        session_id=ownership_limited["session_id"],
        expected_revision=0,
        additions=[
            {"printing_id": "ALT/104", "quantity": 2, "zone": "main_deck"},
            {"printing_id": "SOR/004", "quantity": 1, "zone": "sideboard"},
        ],
        rationale="Attempt to exceed combined owned Guardian copies.",
    )

    assert copy_result["status"] == "fail"
    assert "copy limit" in copy_result["error"]["message"].lower()
    assert _session_bytes(brew_components, copy_limited["session_id"]) == copy_before
    assert ownership_result["status"] == "fail"
    assert ownership_result["collection"]["conflicts"] == [
        {"printing_id": "ALT/104", "requested": 3, "owned": 2}
    ]
    assert _session_bytes(brew_components, ownership_limited["session_id"]) == ownership_before


def test_record_brew_decisions_wrapper_routes_sideboard_with_real_service(
    brew_components: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    service = brew_components["service"]
    monkeypatch.setattr(server, "ai_brew_service", service)
    started = _start(service)

    added = server.swu_record_brew_decisions(
        session_id=started["session_id"],
        expected_revision=0,
        additions=[BrewCardChange(card_id="SOR/005", quantity=1, zone="sideboard")],
        rationale="Add Recaller through the typed wrapper.",
    )
    cut = server.swu_record_brew_decisions(
        session_id=started["session_id"],
        expected_revision=1,
        cuts=[BrewCardChange(card_id="SOR/005", quantity=1, zone="sideboard")],
        rationale="Cut Recaller through the typed wrapper.",
    )
    overflow_brew = _start(service)
    overflow_before = _session_bytes(brew_components, overflow_brew["session_id"])
    overflow = server.swu_record_brew_decisions(
        session_id=overflow_brew["session_id"],
        expected_revision=0,
        additions=[BrewCardChange(card_id="SOR/004", quantity=11, zone="sideboard")],
        rationale="Typed wrapper must reject Premier sideboard overflow.",
    )
    twin_suns = _start(
        service,
        format_name="twin_suns",
        leader_names=["Luke Skywalker - Faithful Friend", "Leia Organa - Rebel Ally"],
    )
    twin_before = _session_bytes(brew_components, twin_suns["session_id"])
    twin_sideboard = server.swu_record_brew_decisions(
        session_id=twin_suns["session_id"],
        expected_revision=0,
        additions=[BrewCardChange(card_id="SOR/004", quantity=1, zone="sideboard")],
        rationale="Typed wrapper must reject a Twin Suns sideboard.",
    )
    stored = service.store.load(started["session_id"])

    assert added["status"] == "ok"
    assert cut["status"] == "ok"
    assert stored.revisions[1].sideboard[0]["lookup_id"] == "SOR/005"
    assert stored.revisions[2].sideboard == []
    assert overflow["status"] == "fail"
    assert "sideboard max" in overflow["error"]["message"].lower()
    assert _session_bytes(brew_components, overflow_brew["session_id"]) == overflow_before
    assert twin_sideboard["status"] == "fail"
    assert "sideboard" in twin_sideboard["error"]["message"].lower()
    assert _session_bytes(brew_components, twin_suns["session_id"]) == twin_before
