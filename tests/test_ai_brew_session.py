import json
import os
import re
from pathlib import Path

import pytest

from swu_mcp.ai_brew_session import (
    BrewDecision,
    BrewPersistenceError,
    BrewReport,
    BrewRevision,
    BrewSession,
    BrewSessionStore,
    canonical_revision_hash,
    generate_session_id,
)


def _stored_card(
    printing_id: str,
    display_name: str,
    card_type: str,
) -> dict[str, object]:
    set_code, number = printing_id.split("/", 1)
    return {
        "lookup_id": printing_id,
        "set_code": set_code,
        "number": number,
        "display_name": display_name,
        "name": display_name,
        "card_type": card_type,
        "aspects": ["Command", "Villainy"],
    }


def make_session(session_id: str = "brew-one") -> BrewSession:
    return BrewSession(
        session_id=session_id,
        created_at="2026-08-15T12:00:00Z",
        updated_at="2026-08-15T12:00:00Z",
        format_name="premier",
        stage="planning",
        leader_cards=[_stored_card("SWH/001", "Leader", "Leader")],
        base_card=_stored_card("SWH/002", "Base", "Base"),
        legal_aspects=["command", "villainy"],
        only_owned=True,
        allow_off_aspect=False,
        collection_path="/tmp/collection.json",
        collection_snapshot_hash="0" * 64,
        collection_refreshes=[],
        theme="midrange pressure",
        target_matchups=["control"],
        meta_context={"season": "premier"},
        revisions=[
            BrewRevision(
                revision=0,
                parent_revision=None,
                created_at="2026-08-15T12:00:00Z",
                thesis="Start with a resilient curve",
                main_deck=[
                    {
                        **_stored_card("SWH/003", "Opening Unit", "Unit"),
                        "quantity": 3,
                    }
                ],
            )
        ],
    )


def _valid_receipt(
    session: BrewSession,
    *,
    revision: int,
    current_report: str | None = None,
    stale_reports: list[str] | None = None,
) -> dict[str, object]:
    return {
        "receipt_id": "receipt-1",
        "finalized_at": "2026-08-15T12:06:00Z",
        "revision": revision,
        "finalized_revision_sha256": canonical_revision_hash(
            session.revisions[revision]
        ),
        "collection": {
            "tracked": True,
            "path": session.collection_path,
            "snapshot_hash": session.collection_snapshot_hash,
            "current_hash": session.collection_snapshot_hash,
            "stale": False,
        },
        "validation": {},
        "analysis": {},
        "export_hashes": {
            "plain_text_sha256": "a" * 64,
            "holoscan_sha256": "b" * 64,
        },
        "current_advisory_report": current_report,
        "stale_advisory_reports": stale_reports or [],
        "decision_history": [
            decision.model_dump(mode="json")
            for decision in session.decisions
            if decision.resulting_revision <= revision
        ],
    }


def test_generated_and_caller_selected_ids_are_filename_safe(tmp_path: Path) -> None:
    generated = generate_session_id()
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", generated)

    store = BrewSessionStore(tmp_path)
    selected = make_session(session_id="my-brew.v1_2")
    created = store.create(selected)
    assert created.session_id == "my-brew.v1_2"
    assert (tmp_path / "my-brew.v1_2.json").exists()


def test_supported_long_set_codes_are_canonical_persisted_ids(tmp_path: Path) -> None:
    session = make_session()
    session.leader_cards[0] = _stored_card(
        "SOROPJ/001",
        "Promotional Leader",
        "Leader",
    )

    BrewSessionStore(tmp_path).create(session)

    assert BrewSessionStore(tmp_path).load("brew-one").leader_cards[0]["lookup_id"] == (
        "SOROPJ/001"
    )


@pytest.mark.parametrize("session_id", ["", "../escape", "a/b", "a\\b", ".", "a" * 81])
def test_create_rejects_invalid_session_ids(tmp_path: Path, session_id: str) -> None:
    with pytest.raises(ValueError, match="session ID"):
        BrewSessionStore(tmp_path).create(make_session(session_id=session_id))


def test_create_rejects_duplicate_ids(tmp_path: Path) -> None:
    store = BrewSessionStore(tmp_path)
    store.create(make_session())
    with pytest.raises(ValueError, match="already exists"):
        store.create(make_session())


def test_conflicting_concurrent_saves_fail_closed(tmp_path: Path) -> None:
    store = BrewSessionStore(tmp_path)
    store.create(make_session())
    first_writer = store.load("brew-one")
    second_writer = BrewSessionStore(tmp_path).load("brew-one")

    first_writer.stage = "drafting"
    store.save(first_writer)
    second_writer.stage = "evaluating"
    with pytest.raises(BrewPersistenceError, match="concurrent"):
        BrewSessionStore(tmp_path).save(second_writer)

    assert store.load("brew-one").stage == "drafting"


def test_leftover_unlocked_lock_file_does_not_block_later_save(tmp_path: Path) -> None:
    store = BrewSessionStore(tmp_path)
    session = make_session()
    store.create(session)
    lock_path = tmp_path / ".brew-one.lock"
    assert lock_path.exists()

    session.stage = "drafting"
    store.save(session)

    assert lock_path.exists()
    assert store.load("brew-one").stage == "drafting"


def test_save_fails_when_same_session_lock_is_held(tmp_path: Path) -> None:
    store = BrewSessionStore(tmp_path)
    session = make_session()
    store.create(session)
    lock_holder = BrewSessionStore(tmp_path)

    with lock_holder._session_lock("brew-one"):
        with pytest.raises(BrewPersistenceError, match="lock"):
            store.save(session)



def test_schema_version_one_serializes_and_reloads_from_new_store(tmp_path: Path) -> None:
    store = BrewSessionStore(tmp_path)
    session = make_session()
    store.create(session)

    session.stage = "drafting"
    session.updated_at = "2026-08-15T12:05:00Z"
    session.revisions.append(
        BrewRevision(
            revision=1,
            parent_revision=0,
            created_at="2026-08-15T12:05:00Z",
            thesis="Add efficient interaction",
            packages=[{"package_id": "removal", "cards": ["Removal"]}],
        )
    )
    session.decisions.append(
        BrewDecision(
            decision_id="decision-1",
            parent_revision=0,
            resulting_revision=1,
            additions=[
                {**_stored_card("SWH/004", "Removal", "Event"), "quantity": 1}
            ],
            cuts=[
                {**_stored_card("SWH/003", "Opening Unit", "Unit"), "quantity": 1}
            ],
            rationale="Improve the control matchup",
            evidence_ids=["report-1"],
            advisory_report_id="report-1",
            accepted_stale_evidence=True,
            created_at="2026-08-15T12:05:00Z",
        )
    )
    session.reports.append(
        BrewReport(
            report_id="report-1",
            revision=1,
            created_at="2026-08-15T12:05:00Z",
            inputs={"seed": 7},
            result={"win_rate": 0.55},
        )
    )
    session.current_revision = 1
    session.finalization_receipts.append(
        _valid_receipt(session, revision=1, current_report="report-1")
    )
    store.save(session)

    raw = json.loads((tmp_path / "brew-one.json").read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert raw["revisions"][0]["revision"] == 0
    assert raw["decisions"][0]["resulting_revision"] == 1
    assert raw["decisions"][0]["accepted_stale_evidence"] is True

    reloaded = BrewSessionStore(tmp_path).load("brew-one")
    assert reloaded.model_dump(mode="json") == session.model_dump(mode="json")
    assert reloaded.finalization_receipts == session.finalization_receipts


def test_decision_defaults_stale_evidence_acceptance_to_false() -> None:
    decision = BrewDecision(
        decision_id="decision-1",
        parent_revision=0,
        resulting_revision=0,
        rationale="Record ordinary current-revision evidence.",
        created_at="2026-08-15T12:05:00Z",
    )

    assert decision.accepted_stale_evidence is False


def test_revisions_are_historical_and_decisions_reports_are_append_only(tmp_path: Path) -> None:
    store = BrewSessionStore(tmp_path)
    session = make_session()
    store.create(session)
    original_revision = session.revisions[0].model_dump(mode="json")

    session.revisions.append(
        BrewRevision(
            revision=1,
            parent_revision=0,
            created_at="2026-08-15T12:10:00Z",
            thesis="Second draft",
        )
    )
    session.decisions.append(
        BrewDecision(
            decision_id="decision-1",
            parent_revision=0,
            resulting_revision=1,
            rationale="Keep the curve",
            created_at="2026-08-15T12:10:00Z",
        )
    )
    session.reports.append(
        BrewReport(
            report_id="report-1",
            revision=1,
            created_at="2026-08-15T12:10:00Z",
            inputs={},
            result={"status": "advisory"},
        )
    )
    session.current_revision = 1
    store.save(session)

    loaded = BrewSessionStore(tmp_path).load("brew-one")
    assert loaded.revisions[0].model_dump(mode="json") == original_revision
    assert [decision.decision_id for decision in loaded.decisions] == ["decision-1"]
    assert [report.report_id for report in loaded.reports] == ["report-1"]


def test_existing_revisions_decisions_and_reports_cannot_be_changed(tmp_path: Path) -> None:
    store = BrewSessionStore(tmp_path)
    session = make_session()
    store.create(session)

    session.revisions[0].thesis = "Changed historical thesis"
    with pytest.raises(ValueError, match="immutable"):
        store.save(session)

    session = store.load("brew-one")
    session.revisions.append(
        BrewRevision(
            revision=1,
            parent_revision=0,
            created_at="2026-08-15T12:10:00Z",
            thesis="Recorded revision",
        )
    )
    session.decisions.append(
        BrewDecision(
            decision_id="decision-1",
            parent_revision=0,
            resulting_revision=1,
            rationale="Recorded decision",
            created_at="2026-08-15T12:10:00Z",
        )
    )
    session.current_revision = 1
    store.save(session)
    session.decisions[0].rationale = "Changed decision"
    with pytest.raises(ValueError, match="append-only"):
        store.save(session)


def test_existing_finalization_receipts_cannot_be_changed(tmp_path: Path) -> None:
    store = BrewSessionStore(tmp_path)
    session = make_session()
    session.finalization_receipts.append(_valid_receipt(session, revision=0))
    store.create(session)

    loaded = store.load("brew-one")
    loaded.finalization_receipts[0]["status"] = "altered"
    with pytest.raises(ValueError, match="receipt"):
        store.save(loaded)


def test_revision_numbers_must_be_unique(tmp_path: Path) -> None:
    store = BrewSessionStore(tmp_path)
    session = make_session()
    session.revisions.append(session.revisions[0].model_copy())
    with pytest.raises(ValueError, match="revision"):
        store.create(session)


def test_revision_numbers_must_be_contiguous(tmp_path: Path) -> None:
    store = BrewSessionStore(tmp_path)
    session = make_session()
    session.revisions[0].revision = 2
    with pytest.raises(ValueError, match="revision"):
        store.create(session)


def test_revision_parent_current_decision_and_report_references_are_valid(tmp_path: Path) -> None:
    store = BrewSessionStore(tmp_path)

    missing_parent = make_session()
    missing_parent.revisions.append(
        BrewRevision(revision=1, parent_revision=7, created_at="2026-08-15T12:01:00Z")
    )
    with pytest.raises(ValueError, match="parent"):
        store.create(missing_parent)

    missing_current = make_session()
    missing_current.current_revision = 3
    with pytest.raises(ValueError, match="current_revision"):
        store.create(missing_current)

    missing_decision = make_session()
    missing_decision.decisions.append(
        BrewDecision(
            decision_id="decision-1",
            parent_revision=4,
            resulting_revision=0,
            rationale="Invalid reference",
            created_at="2026-08-15T12:01:00Z",
        )
    )
    with pytest.raises(ValueError, match="decision"):
        store.create(missing_decision)

    missing_report = make_session()
    missing_report.reports.append(
        BrewReport(
            report_id="report-1",
            revision=4,
            created_at="2026-08-15T12:01:00Z",
            inputs={},
            result={},
        )
    )
    with pytest.raises(ValueError, match="report"):
        store.create(missing_report)


def test_current_revision_must_be_the_latest_immutable_revision(tmp_path: Path) -> None:
    session = make_session()
    session.revisions.append(
        BrewRevision(
            revision=1,
            parent_revision=0,
            created_at="2026-08-15T12:01:00Z",
        )
    )
    session.decisions.append(
        BrewDecision(
            decision_id="decision-1",
            parent_revision=0,
            resulting_revision=1,
            rationale="Create a later revision.",
            created_at="2026-08-15T12:01:00Z",
        )
    )

    with pytest.raises(ValueError, match="current_revision"):
        BrewSessionStore(tmp_path).create(session)


def _write_session_payload(tmp_path: Path, payload: dict[str, object]) -> None:
    (tmp_path / "brew-one.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def test_load_rejects_parent_revisions_that_do_not_precede_the_child(tmp_path: Path) -> None:
    payload = make_session().model_dump(mode="json")
    payload["revisions"].append(
        BrewRevision(
            revision=1,
            parent_revision=1,
            created_at="2026-08-15T12:01:00Z",
        ).model_dump(mode="json")
    )
    payload["decisions"].append(
        BrewDecision(
            decision_id="decision-1",
            parent_revision=1,
            resulting_revision=1,
            rationale="Corrupt self-parent relationship.",
            created_at="2026-08-15T12:01:00Z",
        ).model_dump(mode="json")
    )
    payload["current_revision"] = 1
    _write_session_payload(tmp_path, payload)

    with pytest.raises(BrewPersistenceError, match="parent"):
        BrewSessionStore(tmp_path).load("brew-one")


def test_load_rejects_duplicate_decision_ids_and_mismatched_revision_edges(
    tmp_path: Path,
) -> None:
    payload = make_session().model_dump(mode="json")
    payload["revisions"].extend(
        [
            BrewRevision(
                revision=1,
                parent_revision=0,
                created_at="2026-08-15T12:01:00Z",
            ).model_dump(mode="json"),
            BrewRevision(
                revision=2,
                parent_revision=1,
                created_at="2026-08-15T12:02:00Z",
            ).model_dump(mode="json"),
        ]
    )
    payload["decisions"].extend(
        [
            BrewDecision(
                decision_id="duplicate-decision",
                parent_revision=0,
                resulting_revision=1,
                rationale="First edge.",
                created_at="2026-08-15T12:01:00Z",
            ).model_dump(mode="json"),
            BrewDecision(
                decision_id="duplicate-decision",
                parent_revision=0,
                resulting_revision=2,
                rationale="Mismatched and duplicate edge.",
                created_at="2026-08-15T12:02:00Z",
            ).model_dump(mode="json"),
        ]
    )
    payload["current_revision"] = 2
    _write_session_payload(tmp_path, payload)

    with pytest.raises(BrewPersistenceError, match="decision"):
        BrewSessionStore(tmp_path).load("brew-one")


def test_load_rejects_reordered_decision_relationships(tmp_path: Path) -> None:
    payload = make_session().model_dump(mode="json")
    payload["revisions"].extend(
        [
            BrewRevision(
                revision=1,
                parent_revision=0,
                created_at="2026-08-15T12:01:00Z",
            ).model_dump(mode="json"),
            BrewRevision(
                revision=2,
                parent_revision=1,
                created_at="2026-08-15T12:02:00Z",
            ).model_dump(mode="json"),
        ]
    )
    payload["decisions"] = [
        BrewDecision(
            decision_id="decision-2",
            parent_revision=1,
            resulting_revision=2,
            rationale="Second edge stored first.",
            created_at="2026-08-15T12:02:00Z",
        ).model_dump(mode="json"),
        BrewDecision(
            decision_id="decision-1",
            parent_revision=0,
            resulting_revision=1,
            rationale="First edge stored second.",
            created_at="2026-08-15T12:01:00Z",
        ).model_dump(mode="json"),
    ]
    payload["current_revision"] = 2
    _write_session_payload(tmp_path, payload)

    with pytest.raises(BrewPersistenceError, match="decision"):
        BrewSessionStore(tmp_path).load("brew-one")


def test_load_rejects_coerced_parent_revision_types(tmp_path: Path) -> None:
    payload = make_session().model_dump(mode="json")
    payload["revisions"].append(
        {
            **BrewRevision(
                revision=1,
                parent_revision=0,
                created_at="2026-08-15T12:01:00Z",
            ).model_dump(mode="json"),
            "parent_revision": "0",
        }
    )
    payload["decisions"].append(
        BrewDecision(
            decision_id="decision-1",
            parent_revision=0,
            resulting_revision=1,
            rationale="A string parent must not be silently coerced.",
            created_at="2026-08-15T12:01:00Z",
        ).model_dump(mode="json")
    )
    payload["current_revision"] = 1
    _write_session_payload(tmp_path, payload)

    with pytest.raises(BrewPersistenceError, match="parent_revision"):
        BrewSessionStore(tmp_path).load("brew-one")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("leader_card_id", "swh/1", "canonical"),
        ("collection_snapshot_hash", "not-a-sha256", "SHA-256"),
    ],
)
def test_load_rejects_noncanonical_card_ids_and_invalid_snapshot_hashes(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    payload = make_session().model_dump(mode="json")
    if field == "leader_card_id":
        payload["leader_cards"][0]["lookup_id"] = value
    else:
        payload[field] = value
    _write_session_payload(tmp_path, payload)

    with pytest.raises(BrewPersistenceError, match=message):
        BrewSessionStore(tmp_path).load("brew-one")


def test_load_rejects_conflicting_card_number_aliases(tmp_path: Path) -> None:
    payload = make_session().model_dump(mode="json")
    payload["leader_cards"][0]["card_number"] = "999"
    _write_session_payload(tmp_path, payload)

    with pytest.raises(BrewPersistenceError, match="card_number"):
        BrewSessionStore(tmp_path).load("brew-one")


def test_load_rejects_receipts_with_inconsistent_report_and_revision_provenance(
    tmp_path: Path,
) -> None:
    session = make_session()
    session.reports = [
        BrewReport(
            report_id="report-zero",
            revision=0,
            created_at="2026-08-15T12:01:00Z",
            inputs={},
            result={"revision": 0},
        )
    ]
    payload = session.model_dump(mode="json")
    receipt = _valid_receipt(session, revision=0)
    receipt["current_advisory_report"] = "missing-report"
    payload["finalization_receipts"] = [receipt]
    _write_session_payload(tmp_path, payload)

    with pytest.raises(BrewPersistenceError, match="report"):
        BrewSessionStore(tmp_path).load("brew-one")


def test_load_rejects_receipt_whose_revision_hash_does_not_match(
    tmp_path: Path,
) -> None:
    payload = make_session().model_dump(mode="json")
    payload["finalization_receipts"] = [
        {
            "receipt_id": "receipt-1",
            "finalized_at": "2026-08-15T12:02:00Z",
            "revision": 0,
            "finalized_revision_sha256": "f" * 64,
            "export_hashes": {
                "plain_text_sha256": "a" * 64,
                "holoscan_sha256": "b" * 64,
            },
            "current_advisory_report": None,
            "stale_advisory_reports": [],
            "decision_history": [],
        }
    ]
    _write_session_payload(tmp_path, payload)

    with pytest.raises(BrewPersistenceError, match="revision hash"):
        BrewSessionStore(tmp_path).load("brew-one")


def test_load_rejects_incomplete_receipt_decision_history(tmp_path: Path) -> None:
    session = make_session()
    session.revisions.append(
        BrewRevision(
            revision=1,
            parent_revision=0,
            created_at="2026-08-15T12:01:00Z",
        )
    )
    session.decisions.append(
        BrewDecision(
            decision_id="decision-1",
            parent_revision=0,
            resulting_revision=1,
            rationale="Create the finalized revision.",
            created_at="2026-08-15T12:01:00Z",
        )
    )
    session.current_revision = 1
    payload = session.model_dump(mode="json")
    receipt = _valid_receipt(session, revision=1)
    receipt["decision_history"] = []
    payload["finalization_receipts"] = [receipt]
    _write_session_payload(tmp_path, payload)

    with pytest.raises(BrewPersistenceError, match="decision history"):
        BrewSessionStore(tmp_path).load("brew-one")


def test_load_rejects_invalid_receipt_collection_hashes(tmp_path: Path) -> None:
    session = make_session()
    receipt = _valid_receipt(session, revision=0)
    receipt["collection"]["current_hash"] = "not-a-sha256"
    payload = session.model_dump(mode="json")
    payload["finalization_receipts"] = [receipt]
    _write_session_payload(tmp_path, payload)

    with pytest.raises(BrewPersistenceError, match="collection current hash"):
        BrewSessionStore(tmp_path).load("brew-one")


def test_unsupported_schema_and_corrupt_json_do_not_rewrite_file(tmp_path: Path) -> None:
    store = BrewSessionStore(tmp_path)
    target = tmp_path / "brew-one.json"

    unsupported = b'{"schema_version": 99, "session_id": "brew-one"}\n'
    target.write_bytes(unsupported)
    with pytest.raises(BrewPersistenceError, match="Unsupported schema"):
        store.load("brew-one")
    assert target.read_bytes() == unsupported

    corrupt = b'{not valid json\n'
    target.write_bytes(corrupt)
    with pytest.raises(BrewPersistenceError, match="Could not load"):
        store.load("brew-one")
    assert target.read_bytes() == corrupt

    non_object = b"[]\n"
    target.write_bytes(non_object)
    with pytest.raises(BrewPersistenceError, match="Could not load"):
        store.load("brew-one")
    assert target.read_bytes() == non_object


def test_load_rejects_filename_and_payload_session_id_mismatch(tmp_path: Path) -> None:
    store = BrewSessionStore(tmp_path)
    target = tmp_path / "brew-one.json"
    target.write_text(
        json.dumps(make_session(session_id="brew-two").model_dump(mode="json")),
        encoding="utf-8",
    )

    with pytest.raises(BrewPersistenceError, match="session ID mismatch"):
        store.load("brew-one")


def test_save_is_atomic_when_replace_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = BrewSessionStore(tmp_path)
    session = make_session(session_id="brew-one")
    store.create(session)
    original = (tmp_path / "brew-one.json").read_bytes()

    def fail_replace(source, destination):
        raise OSError("injected replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    session.stage = "drafting"
    with pytest.raises(BrewPersistenceError, match="replace failure"):
        store.save(session)

    assert (tmp_path / "brew-one.json").read_bytes() == original
    assert store.load("brew-one").stage == "planning"


@pytest.mark.parametrize("post_replace_fault", ["directory_open", "directory_fsync", "directory_close"])
def test_save_treats_replace_as_commit_point_after_directory_sync_fault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    post_replace_fault: str,
) -> None:
    store = BrewSessionStore(tmp_path)
    session = make_session(session_id="brew-one")
    store.create(session)
    target = tmp_path / "brew-one.json"
    original = target.read_bytes()
    session.stage = "drafting"

    if post_replace_fault == "directory_open":
        original_open = os.open

        def fail_directory_open(path, flags, mode=0o777):
            if Path(path) == tmp_path:
                raise OSError("injected directory open failure")
            return original_open(path, flags, mode)

        monkeypatch.setattr(os, "open", fail_directory_open)
    elif post_replace_fault == "directory_fsync":
        original_fsync = os.fsync
        fsync_calls = 0

        def fail_directory_fsync(fd: int) -> None:
            nonlocal fsync_calls
            fsync_calls += 1
            if fsync_calls == 2:
                raise OSError("injected directory fsync failure")
            original_fsync(fd)

        monkeypatch.setattr(os, "fsync", fail_directory_fsync)
    else:
        original_open = os.open
        original_close = os.close
        directory_fd: int | None = None

        def capture_directory_open(path, flags, mode=0o777):
            nonlocal directory_fd
            fd = original_open(path, flags, mode)
            if Path(path) == tmp_path:
                directory_fd = fd
            return fd

        def fail_directory_close(fd: int) -> None:
            if fd == directory_fd:
                raise OSError("injected directory close failure")
            original_close(fd)

        monkeypatch.setattr(os, "open", capture_directory_open)
        monkeypatch.setattr(os, "close", fail_directory_close)

    with pytest.warns(RuntimeWarning, match="durability"):
        store.save(session)

    assert target.read_bytes() != original
    assert BrewSessionStore(tmp_path).load("brew-one").stage == "drafting"
