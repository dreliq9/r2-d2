from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import swu_mcp.ai_brew_service as ai_brew_service_module
from swu_mcp.ai_brew_service import AIBrewService
from swu_mcp.ai_brew_session import (
    BrewDecision,
    BrewPersistenceError,
    BrewRevision,
    BrewSessionStore,
)
from swu_mcp.card_service import CardService
from swu_mcp.collection_service import CollectionService
from swu_mcp.config import Settings
from swu_mcp.deck_service import DeckService


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


@pytest.fixture
def finalization_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, object]:
    cards = [
        _card(
            1,
            "Finalization Leader",
            "Leader",
            subtitle="Mentor",
            aspects=["Vigilance", "Heroism"],
        ),
        _card(
            2,
            "Finalization Partner",
            "Leader",
            subtitle="Ally",
            aspects=["Command", "Heroism"],
        ),
        _card(3, "Finalization Base", "Base", aspects=["Vigilance"]),
        _card(
            84,
            "Finalization Rival",
            "Leader",
            subtitle="Rival",
            aspects=["Cunning", "Villainy"],
        ),
        _card(85, "Off Aspect Unit", "Unit", aspects=["Aggression"], cost="3"),
        _card(
            86,
            "Finalization Unowned Leader",
            "Leader",
            subtitle="Visitor",
            aspects=["Vigilance", "Heroism"],
        ),
        _card(87, "Finalization Reserve Unit", "Unit", aspects=["Vigilance", "Heroism"], cost="2"),
    ]
    cards.extend(
        _card(
            number,
            f"Finalization Unit {number:03d}",
            "Unit",
            aspects=["Vigilance", "Heroism"],
            cost=str(1 + number % 4),
        )
        for number in range(4, 84)
    )
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
                    for number in [1, 2, 3, *range(4, 86)]
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
        "leader_names": ["Finalization Leader - Mentor"],
        "base_name": "Finalization Base",
        "theme": "resilient Jedi midrange",
        "target_matchups": ["aggro"],
        "meta_context": {"season": "test"},
        "only_owned": False,
    }
    request.update(overrides)
    result = service.start_brew(**request)  # type: ignore[arg-type]
    assert result["status"] == "ok"
    return result


def _entry(number: int, quantity: int = 1) -> dict[str, object]:
    return {"printing_id": f"FIN/{number:03d}", "quantity": quantity}


def _premier_entries() -> list[dict[str, object]]:
    return [*[_entry(number, 3) for number in range(4, 20)], _entry(20, 2)]


def _twin_suns_entries() -> list[dict[str, object]]:
    return [_entry(number) for number in range(4, 84)]


def _complete_revision(
    service: AIBrewService,
    session_id: str,
    *,
    entries: list[dict[str, object]],
) -> None:
    result = service.record_decisions(
        session_id=session_id,
        expected_revision=0,
        additions=entries,
        rationale="Record the complete deck before finalization.",
    )
    assert result["status"] == "ok"


def _stored_card(service: AIBrewService, number: int) -> dict[str, object]:
    card = service.card_service.catalog.lookup("FIN", f"{number:03d}")
    assert card is not None
    return card.to_dict()


def _seed_current_main_deck(
    service: AIBrewService,
    session_id: str,
    entries: list[tuple[int, int]],
    *,
    sideboard: list[tuple[int, int]] | None = None,
) -> None:
    session = service.store.load(session_id)
    assert session.current_revision == 0
    created_at = "2026-08-15T12:00:00+00:00"
    main_deck: list[dict[str, object]] = []
    for number, quantity in entries:
        if number == 999:
            main_deck.append(
                {
                    "lookup_id": "FIN/999",
                    "printing_id": "FIN/999",
                    "set_code": "FIN",
                    "number": "999",
                    "display_name": "Missing Finalization Unit",
                    "card_type": "Unit",
                    "aspects": ["Vigilance", "Heroism"],
                    "quantity": quantity,
                }
            )
        else:
            main_deck.append({**_stored_card(service, number), "quantity": quantity})
    session.revisions.append(
        BrewRevision(
            revision=1,
            parent_revision=0,
            created_at=created_at,
            main_deck=main_deck,
            sideboard=[
                {**_stored_card(service, number), "quantity": quantity}
                for number, quantity in (sideboard or [])
            ],
        )
    )
    session.decisions.append(
        BrewDecision(
            decision_id="seed-finalization-test-revision",
            parent_revision=0,
            resulting_revision=1,
            rationale="Seed an immutable revision for finalization validation.",
            created_at=created_at,
        )
    )
    session.current_revision = 1
    session.updated_at = created_at
    session.stage = "drafting"
    service.store.save(session)


def _assert_not_finalized(service: AIBrewService, session_id: str) -> None:
    session = service.store.load(session_id)
    assert session.stage != "finalized"
    assert session.finalization_receipts == []


def _round_tripped_sections(service: AIBrewService, holoscan: str, format_name: str) -> dict[str, list[tuple[str, int]]]:
    round_tripped = service.deck_service.resolve_deck(
        service.deck_service.parse_decklist(decklist=holoscan, format_name=format_name)
    )
    return {
        "leaders": [(str(entry.lookup_id), entry.quantity) for entry in round_tripped.leaders],
        "bases": [(str(entry.lookup_id), entry.quantity) for entry in round_tripped.bases],
        "main_deck": [(str(entry.lookup_id), entry.quantity) for entry in round_tripped.main_deck],
        "sideboard": [(str(entry.lookup_id), entry.quantity) for entry in round_tripped.sideboard],
    }


def test_finalize_premier_returns_provenance_exports_receipt_and_reloads(
    finalization_components: dict[str, object]
) -> None:
    service = finalization_components["service"]
    started = _start(service, only_owned=True)
    session_id = str(started["session_id"])
    _complete_revision(service, session_id, entries=_premier_entries())
    first_report = service.evaluate_brew(session_id=session_id)
    assert first_report["status"] == "ok"
    report = service.evaluate_brew(session_id=session_id)
    assert report["status"] == "ok"

    result = service.finalize_brew(session_id=session_id, expected_revision=1)

    assert result["status"] == "ok"
    assert result["stage"] == "finalized"
    assert result["revision"] == 1
    assert result["validation"]["legal"] is True
    assert result["validation"]["counts"] == {
        "leaders": 1,
        "bases": 1,
        "main_deck": 50,
        "sideboard": 0,
    }
    assert result["analysis"]["deck_size"] == 50
    assert result["collection"]["snapshot_hash"] == started["collection_snapshot"]["sha256"]
    assert result["collection"]["stale"] is False
    assert result["advisory_reports"] == {"current": report["report_id"], "stale": []}
    persisted_before_receipt_check = service.store.load(session_id)
    latest_report = persisted_before_receipt_check.reports[-1]
    assert result["latest_mathematical_report"] == latest_report.result
    assert result["decision_history"] == [
        decision.model_dump(mode="json")
        for decision in service.store.load(session_id).decisions
    ]
    assert result["plain_text"]["export_format"] == "plain_text"
    assert result["holoscan"]["export_format"] == "holoscan"

    round_tripped = service.deck_service.resolve_deck(
        service.deck_service.parse_decklist(
            decklist=result["holoscan"]["deck"], format_name="premier"
        )
    )
    assert [(entry.lookup_id, entry.quantity) for entry in round_tripped.main_deck] == [
        (f"FIN/{number:03d}", 3) for number in range(4, 20)
    ] + [("FIN/020", 2)]

    receipt = result["receipt"]
    assert receipt["revision"] == 1
    assert receipt["validation"] == result["validation"]
    assert receipt["analysis"] == result["analysis"]
    assert receipt["collection"] == result["collection"]
    assert receipt["current_advisory_report"] == report["report_id"]
    assert receipt["decision_history"] == result["decision_history"]
    assert receipt["finalized_revision_sha256"] == hashlib.sha256(
        json.dumps(
            persisted_before_receipt_check.revisions[1].model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert receipt["export_hashes"] == {
        "plain_text_sha256": hashlib.sha256(result["plain_text"]["deck"].encode()).hexdigest(),
        "holoscan_sha256": hashlib.sha256(result["holoscan"]["deck"].encode()).hexdigest(),
    }

    reloaded_service = AIBrewService(
        service.card_service,
        CollectionService(finalization_components["collection_path"]),
        DeckService(service.card_service),
        BrewSessionStore(service.store.root),
    )
    reloaded = reloaded_service.get_context(session_id=session_id, intent="session-summary")
    persisted = reloaded_service.store.load(session_id)
    assert reloaded["session"]["stage"] == "finalized"
    assert persisted.finalization_receipts == [receipt]


def test_finalize_requires_tracked_collection_provenance(
    finalization_components: dict[str, object]
) -> None:
    service = finalization_components["service"]
    started = _start(service, only_owned=False)
    session_id = str(started["session_id"])
    _complete_revision(service, session_id, entries=_premier_entries())
    session = service.store.load(session_id)
    session.collection_path = None
    session.collection_snapshot_hash = None
    service.store.save(session)

    result = service.finalize_brew(session_id=session_id, expected_revision=1)

    assert result["status"] == "fail"
    assert "provenance" in result["error"]["message"].lower()
    _assert_not_finalized(service, session_id)


def test_finalize_rechecks_collection_after_receipt_construction(
    finalization_components: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    service = finalization_components["service"]
    collection_path = finalization_components["collection_path"]
    started = _start(service, only_owned=False)
    session_id = str(started["session_id"])
    _complete_revision(service, session_id, entries=_premier_entries())
    target = service.store.root / f"{session_id}.json"
    before = target.read_bytes()
    original_uuid4 = ai_brew_service_module.uuid4

    def create_receipt_then_change_collection() -> object:
        payload = json.loads(collection_path.read_text(encoding="utf-8"))
        payload["changed_during_receipt_construction"] = True
        collection_path.write_text(json.dumps(payload), encoding="utf-8")
        return original_uuid4()

    monkeypatch.setattr(ai_brew_service_module, "uuid4", create_receipt_then_change_collection)

    result = service.finalize_brew(session_id=session_id, expected_revision=1)

    assert result["status"] == "fail"
    assert "changed during finalization" in result["error"]["message"].lower()
    assert target.read_bytes() == before
    _assert_not_finalized(service, session_id)


def test_finalize_premier_allows_ten_sideboard_cards_and_round_trips_every_zone(
    finalization_components: dict[str, object]
) -> None:
    service = finalization_components["service"]
    started = _start(service)
    session_id = str(started["session_id"])
    _seed_current_main_deck(
        service,
        session_id,
        [*[(number, 3) for number in range(4, 20)], (20, 2)],
        sideboard=[(21, 3), (22, 3), (23, 3), (24, 1)],
    )

    result = service.finalize_brew(session_id=session_id, expected_revision=1)

    assert result["status"] == "ok"
    assert result["validation"]["counts"] == {
        "leaders": 1,
        "bases": 1,
        "main_deck": 50,
        "sideboard": 10,
    }
    assert _round_tripped_sections(service, result["holoscan"]["deck"], "premier") == {
        "leaders": [("FIN/001", 1)],
        "bases": [("FIN/003", 1)],
        "main_deck": [
            *[(f"FIN/{number:03d}", 3) for number in range(4, 20)],
            ("FIN/020", 2),
        ],
        "sideboard": [
            ("FIN/021", 3),
            ("FIN/022", 3),
            ("FIN/023", 3),
            ("FIN/024", 1),
        ],
    }


def test_finalize_rejects_sideboards_over_premier_limit_and_in_twin_suns(
    finalization_components: dict[str, object]
) -> None:
    service = finalization_components["service"]
    premier = _start(service)
    premier_id = str(premier["session_id"])
    _seed_current_main_deck(
        service,
        premier_id,
        [*[(number, 3) for number in range(4, 20)], (20, 2)],
        sideboard=[(21, 3), (22, 3), (23, 3), (24, 2)],
    )

    premier_result = service.finalize_brew(session_id=premier_id, expected_revision=1)

    assert premier_result["status"] == "fail"
    assert "sideboard max is 10" in premier_result["error"]["message"].lower()
    _assert_not_finalized(service, premier_id)

    twin_suns = _start(
        service,
        format_name="twin_suns",
        leader_names=["Finalization Leader - Mentor", "Finalization Partner - Ally"],
    )
    twin_suns_id = str(twin_suns["session_id"])
    _seed_current_main_deck(
        service,
        twin_suns_id,
        [(number, 1) for number in range(4, 84)],
        sideboard=[(87, 1)],
    )

    twin_suns_result = service.finalize_brew(session_id=twin_suns_id, expected_revision=1)

    assert twin_suns_result["status"] == "fail"
    assert "should not include a sideboard" in twin_suns_result["error"]["message"].lower()
    _assert_not_finalized(service, twin_suns_id)


def test_finalize_twin_suns_requires_two_compatible_leaders_and_80_singletons(
    finalization_components: dict[str, object]
) -> None:
    service = finalization_components["service"]
    started = _start(
        service,
        format_name="twin_suns",
        leader_names=["Finalization Leader - Mentor", "Finalization Partner - Ally"],
        only_owned=True,
    )
    session_id = str(started["session_id"])
    _complete_revision(service, session_id, entries=_twin_suns_entries())

    result = service.finalize_brew(session_id=session_id, expected_revision=1)

    assert result["status"] == "ok"
    assert result["validation"]["counts"] == {
        "leaders": 2,
        "bases": 1,
        "main_deck": 80,
        "sideboard": 0,
    }
    assert result["analysis"]["deck_size"] == 80
    assert result["validation"]["legal"] is True


@pytest.mark.parametrize(
    ("entries", "leaders", "message"),
    [
        ([(number, 1) for number in range(4, 83)], None, "exactly 80"),
        ([(4, 2), *[(number, 1) for number in range(5, 83)]], None, "copy limit"),
        (
            [(number, 1) for number in range(4, 84)],
            [1, 84],
            "share Heroism or Villainy",
        ),
    ],
)
def test_finalize_rejects_noncompliant_twin_suns_structure(
    finalization_components: dict[str, object],
    entries: list[tuple[int, int]],
    leaders: list[int] | None,
    message: str,
) -> None:
    service = finalization_components["service"]
    started = _start(
        service,
        format_name="twin_suns",
        leader_names=["Finalization Leader - Mentor", "Finalization Partner - Ally"],
    )
    session_id = str(started["session_id"])
    _seed_current_main_deck(service, session_id, entries)
    if leaders is not None:
        session = service.store.load(session_id)
        session.leader_cards = [_stored_card(service, number) for number in leaders]
        session.legal_aspects = ["Cunning", "Heroism", "Vigilance", "Villainy"]
        service.store.save(session)

    result = service.finalize_brew(session_id=session_id, expected_revision=1)

    assert result["status"] == "fail"
    assert message in result["error"]["message"]
    _assert_not_finalized(service, session_id)


@pytest.mark.parametrize(
    ("entries", "only_owned", "collection_count", "message"),
    [
        ([], False, 3, "at least 50"),
        ([(4, 4)], False, 3, "copy limit"),
        (
            [*[(number, 3) for number in range(4, 20)], (20, 2)],
            True,
            2,
            "ownership conflicts",
        ),
    ],
)
def test_finalize_rejects_noncompliant_premier_structure_and_ownership(
    finalization_components: dict[str, object],
    entries: list[tuple[int, int]],
    only_owned: bool,
    collection_count: int,
    message: str,
) -> None:
    service = finalization_components["service"]
    collection_path = finalization_components["collection_path"]
    if only_owned:
        payload = json.loads(collection_path.read_text(encoding="utf-8"))
        for entry in payload["entries"]:
            if entry["set_code"] == "FIN" and entry["card_number"] == "004":
                entry["count"] = collection_count
        collection_path.write_text(json.dumps(payload), encoding="utf-8")
    started = _start(service, only_owned=only_owned)
    session_id = str(started["session_id"])
    _seed_current_main_deck(service, session_id, entries)

    result = service.finalize_brew(session_id=session_id, expected_revision=1)

    assert result["status"] == "fail"
    assert message in result["error"]["message"].lower()
    _assert_not_finalized(service, session_id)


def test_finalize_rejects_unresolved_cards_and_illegal_aspects_without_receipts(
    finalization_components: dict[str, object]
) -> None:
    service = finalization_components["service"]
    unresolved = _start(service)
    unresolved_id = str(unresolved["session_id"])
    _seed_current_main_deck(
        service,
        unresolved_id,
        [*[(number, 3) for number in range(4, 20)], (20, 1), (999, 1)],
    )

    unresolved_result = service.finalize_brew(session_id=unresolved_id, expected_revision=1)

    assert unresolved_result["status"] == "fail"
    assert "could not resolve" in unresolved_result["error"]["message"].lower()
    _assert_not_finalized(service, unresolved_id)

    off_aspect = _start(service)
    off_aspect_id = str(off_aspect["session_id"])
    _seed_current_main_deck(service, off_aspect_id, [
        *[(number, 3) for number in range(4, 19)],
        (19, 2),
        (85, 3),
    ])

    off_aspect_result = service.finalize_brew(session_id=off_aspect_id, expected_revision=1)

    assert off_aspect_result["status"] == "fail"
    assert "off-aspect" in off_aspect_result["error"]["message"].lower()
    _assert_not_finalized(service, off_aspect_id)


def test_finalize_rejects_unowned_persisted_setup_cards_without_receipts(
    finalization_components: dict[str, object]
) -> None:
    service = finalization_components["service"]
    started = _start(service, only_owned=True)
    session_id = str(started["session_id"])
    _seed_current_main_deck(
        service,
        session_id,
        [*[(number, 3) for number in range(4, 20)], (20, 2)],
    )
    session = service.store.load(session_id)
    session.leader_cards = [_stored_card(service, 86)]
    service.store.save(session)

    result = service.finalize_brew(session_id=session_id, expected_revision=1)

    assert result["status"] == "fail"
    assert "ownership" in result["error"]["message"].lower()
    _assert_not_finalized(service, session_id)


def test_finalize_rejects_stale_revision_and_stale_collection_without_receipts(
    finalization_components: dict[str, object]
) -> None:
    service = finalization_components["service"]
    stale_revision = _start(service)
    stale_revision_id = str(stale_revision["session_id"])
    _complete_revision(service, stale_revision_id, entries=_premier_entries())

    stale_revision_result = service.finalize_brew(session_id=stale_revision_id, expected_revision=0)

    assert stale_revision_result["status"] == "fail"
    assert "expected revision" in stale_revision_result["error"]["message"].lower()
    _assert_not_finalized(service, stale_revision_id)

    stale_collection = _start(service, only_owned=True)
    stale_collection_id = str(stale_collection["session_id"])
    _complete_revision(service, stale_collection_id, entries=_premier_entries())
    collection_path = finalization_components["collection_path"]
    payload = json.loads(collection_path.read_text(encoding="utf-8"))
    payload["changed_after_start"] = True
    collection_path.write_text(json.dumps(payload), encoding="utf-8")

    stale_collection_result = service.finalize_brew(
        session_id=stale_collection_id, expected_revision=1
    )

    assert stale_collection_result["status"] == "fail"
    assert "collection changed" in stale_collection_result["error"]["message"].lower()
    _assert_not_finalized(service, stale_collection_id)


def test_finalize_identifies_stale_advisory_reports_without_treating_them_as_current(
    finalization_components: dict[str, object]
) -> None:
    service = finalization_components["service"]
    started = _start(service)
    session_id = str(started["session_id"])
    _complete_revision(service, session_id, entries=_premier_entries())
    older_report = service.evaluate_brew(session_id=session_id)
    assert older_report["status"] == "ok"
    advanced = service.record_decisions(
        session_id=session_id,
        expected_revision=1,
        additions=[_entry(21)],
        cuts=[_entry(20)],
        rationale="Advance past the advisory report without changing deck size.",
    )
    assert advanced["status"] == "ok"

    result = service.finalize_brew(session_id=session_id, expected_revision=2)

    assert result["status"] == "ok"
    assert result["advisory_reports"] == {
        "current": None,
        "stale": [older_report["report_id"]],
    }
    assert result["receipt"]["current_advisory_report"] is None
    assert result["receipt"]["stale_advisory_reports"] == [older_report["report_id"]]


def test_finalize_save_failure_leaves_stage_and_receipts_unchanged(
    finalization_components: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    service = finalization_components["service"]
    started = _start(service)
    session_id = str(started["session_id"])
    _complete_revision(service, session_id, entries=_premier_entries())
    target = service.store.root / f"{session_id}.json"
    before = target.read_bytes()

    def fail_save(_session: object) -> None:
        raise BrewPersistenceError("injected finalization save failure")

    monkeypatch.setattr(service.store, "save", fail_save)

    result = service.finalize_brew(session_id=session_id, expected_revision=1)

    assert result["status"] == "fail"
    assert target.read_bytes() == before
    persisted = BrewSessionStore(service.store.root).load(session_id)
    assert persisted.stage != "finalized"
    assert persisted.finalization_receipts == []


def test_finalize_malformed_export_leaves_stage_and_receipts_unchanged(
    finalization_components: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    service = finalization_components["service"]
    started = _start(service)
    session_id = str(started["session_id"])
    _complete_revision(service, session_id, entries=_premier_entries())
    target = service.store.root / f"{session_id}.json"
    before = target.read_bytes()

    def malformed_export(**_kwargs: object) -> dict[str, str]:
        return {"export_format": "plain_text"}

    monkeypatch.setattr(service.deck_service, "export_deck", malformed_export)

    result = service.finalize_brew(session_id=session_id, expected_revision=1)

    assert result["status"] == "fail"
    assert target.read_bytes() == before
    _assert_not_finalized(service, session_id)
