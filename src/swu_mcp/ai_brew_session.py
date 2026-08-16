"""Durable session records for the caller-managed AI brew workflow."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, PrivateAttr, ValidationError

if os.name == "nt":
    import msvcrt
else:
    import fcntl


SCHEMA_VERSION = 1
_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_PRINTING_ID_PATTERN = re.compile(
    r"^[A-Z][A-Z0-9]{1,7}/(?:[0-9]{3}[A-Za-z]?|T[0-9]{2})$"
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ABSENT_SHA256_PATTERN = re.compile(r"^absent:v1:[0-9a-f]{64}$")


class BrewPersistenceError(RuntimeError):
    """Raised when a brew session cannot be safely read or persisted."""


class BrewRevision(BaseModel):
    revision: int
    parent_revision: int | None
    created_at: str
    thesis: str = ""
    packages: list[dict[str, Any]] = Field(default_factory=list)
    role_targets: dict[str, int] = Field(default_factory=dict)
    main_deck: list[dict[str, Any]] = Field(default_factory=list)
    sideboard: list[dict[str, Any]] = Field(default_factory=list)
    reservations: list[dict[str, Any]] = Field(default_factory=list)
    rejected_cards: list[dict[str, Any]] = Field(default_factory=list)


class BrewDecision(BaseModel):
    decision_id: str
    parent_revision: int
    resulting_revision: int
    additions: list[dict[str, Any]] = Field(default_factory=list)
    cuts: list[dict[str, Any]] = Field(default_factory=list)
    thesis: str | None = None
    packages: list[dict[str, Any]] | None = None
    role_targets: dict[str, int] | None = None
    reservations: list[dict[str, Any]] | None = None
    rejected_cards: list[dict[str, Any]] | None = None
    rationale: str
    evidence_ids: list[str] = Field(default_factory=list)
    advisory_report_id: str | None = None
    accepted_stale_evidence: bool = False
    created_at: str


class BrewReport(BaseModel):
    report_id: str
    revision: int
    created_at: str
    inputs: dict[str, Any]
    result: dict[str, Any]


class BrewSession(BaseModel):
    schema_version: Literal[1] = 1
    session_id: str
    created_at: str
    updated_at: str
    format_name: Literal["premier", "twin_suns"]
    stage: Literal["planning", "drafting", "evaluating", "revising", "finalized"]
    leader_cards: list[dict[str, Any]]
    base_card: dict[str, Any]
    legal_aspects: list[str]
    only_owned: bool
    allow_off_aspect: bool
    collection_path: str | None
    collection_snapshot_hash: str | None
    collection_refreshes: list[dict[str, Any]] = Field(default_factory=list)
    theme: str
    target_matchups: list[str] = Field(default_factory=list)
    meta_context: dict[str, Any] = Field(default_factory=dict)
    revisions: list[BrewRevision]
    decisions: list[BrewDecision] = Field(default_factory=list)
    reports: list[BrewReport] = Field(default_factory=list)
    current_revision: int = 0
    finalization_receipts: list[dict[str, Any]] = Field(default_factory=list)
    _persisted_fingerprint: str | None = PrivateAttr(default=None)


def canonical_revision_hash(revision: BrewRevision) -> str:
    """Return the stable SHA-256 of one JSON-canonical immutable revision."""

    payload = json.dumps(
        revision.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_sha256(value: object, label: str, *, allow_absent: bool = False) -> str:
    if not isinstance(value, str) or not (
        _SHA256_PATTERN.fullmatch(value)
        or (allow_absent and _ABSENT_SHA256_PATTERN.fullmatch(value))
    ):
        raise ValueError(f"{label} must be a lowercase SHA-256 value")
    return value


def _validate_card_identifier(card: object, label: str) -> None:
    if not isinstance(card, dict):
        raise ValueError(f"{label} must be a card object with a canonical printing ID")
    lookup_id = card.get("lookup_id")
    printing_id = card.get("printing_id")
    if lookup_id is not None and printing_id is not None and lookup_id != printing_id:
        raise ValueError(f"{label} has conflicting canonical printing IDs")
    identifier = lookup_id or printing_id
    if not isinstance(identifier, str) or not _PRINTING_ID_PATTERN.fullmatch(identifier):
        raise ValueError(f"{label} lacks a canonical SET/NNN printing ID")
    set_code, number = identifier.split("/", 1)
    stored_set = card.get("set_code")
    if stored_set is not None and stored_set != set_code:
        raise ValueError(f"{label} set_code conflicts with its canonical printing ID")
    for field in ("number", "card_number"):
        stored_number = card.get(field)
        if stored_number is not None and str(stored_number) != number:
            raise ValueError(
                f"{label} {field} conflicts with its canonical printing ID"
            )


def generate_session_id() -> str:
    """Return a unique, filename-safe session identifier."""

    return uuid4().hex


class BrewSessionStore:
    """Persist complete brew sessions as atomically replaced JSON files."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, session: BrewSession) -> BrewSession:
        self._validate_session_id(session.session_id)
        target = self._target_for(session.session_id)
        with self._session_lock(session.session_id):
            if target.exists():
                raise ValueError(f"Brew session ID already exists: {session.session_id}")
            self._validate_session(session)
            self._persist_atomic(session, target)
            session._persisted_fingerprint = self._file_fingerprint(target)
        return session

    def load(self, session_id: str) -> BrewSession:
        target = self._target_for(session_id)
        with self._session_lock(session_id):
            return self._load_unlocked(target, session_id)

    def save(self, session: BrewSession) -> None:
        self._validate_session_id(session.session_id)
        target = self._target_for(session.session_id)
        with self._session_lock(session.session_id):
            self._validate_session(session)
            if target.exists():
                if session._persisted_fingerprint is None:
                    raise BrewPersistenceError(
                        "Could not persist brew session: no baseline for concurrent-save check"
                    )
                if self._file_fingerprint(target) != session._persisted_fingerprint:
                    raise BrewPersistenceError(
                        "Could not persist brew session: concurrent modification detected"
                    )
                previous = self._load_unlocked(target, session.session_id)
                self._validate_append_only_history(previous, session)
            elif session._persisted_fingerprint is not None:
                raise BrewPersistenceError(
                    "Could not persist brew session: session file disappeared"
                )

            self._persist_atomic(session, target)
            session._persisted_fingerprint = self._file_fingerprint(target)

    def _load_unlocked(self, target: Path, session_id: str) -> BrewSession:
        try:
            raw = target.read_bytes()
            payload = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BrewPersistenceError(f"Could not load brew session: {exc}") from exc

        if not isinstance(payload, dict):
            raise BrewPersistenceError("Could not load brew session: JSON root must be an object")
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise BrewPersistenceError(
                f"Unsupported schema version: {payload.get('schema_version')!r}"
            )
        if payload.get("session_id") != session_id:
            raise BrewPersistenceError(
                f"session ID mismatch: requested {session_id!r}, "
                f"payload contains {payload.get('session_id')!r}"
            )
        try:
            session = BrewSession.model_validate(payload, strict=True)
            self._validate_session(session)
        except (ValidationError, ValueError) as exc:
            raise BrewPersistenceError(f"Could not load brew session: {exc}") from exc
        session._persisted_fingerprint = hashlib.sha256(raw).hexdigest()
        return session

    @staticmethod
    def _file_fingerprint(target: Path) -> str:
        try:
            return hashlib.sha256(target.read_bytes()).hexdigest()
        except OSError as exc:
            raise BrewPersistenceError(
                f"Could not inspect brew session for concurrent-save check: {exc}"
            ) from exc

    def _persist_atomic(self, session: BrewSession, target: Path) -> None:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{session.session_id}.",
            suffix=".tmp",
            dir=self.root,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(session.model_dump(mode="json"), handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        except Exception as exc:
            Path(temp_name).unlink(missing_ok=True)
            raise BrewPersistenceError(f"Could not persist brew session: {exc}") from exc

        try:
            directory_fd = os.open(self.root, os.O_RDONLY)
        except OSError as exc:
            warnings.warn(
                "Brew session atomic replace succeeded, but directory durability "
                f"could not be confirmed: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
            return
        durability_error: OSError | None = None
        try:
            os.fsync(directory_fd)
        except OSError as exc:
            durability_error = exc
        finally:
            try:
                os.close(directory_fd)
            except OSError as exc:
                if durability_error is None:
                    durability_error = exc
        if durability_error is not None:
            warnings.warn(
                "Brew session atomic replace succeeded, but directory durability "
                f"could not be confirmed: {durability_error}",
                RuntimeWarning,
                stacklevel=2,
            )

    @contextmanager
    def _session_lock(self, session_id: str) -> Iterator[None]:
        lock_path = self.root / f".{session_id}.lock"
        lock_fd: int | None = None
        acquired = False
        release_error: BrewPersistenceError | None = None
        try:
            try:
                lock_fd = os.open(
                    lock_path,
                    os.O_CREAT | os.O_RDWR,
                    0o600,
                )
                self._acquire_advisory_lock(lock_fd)
                acquired = True
            except OSError as exc:
                raise BrewPersistenceError(
                    f"Could not acquire brew session lock for {session_id}: "
                    f"another writer is active or the lock is unavailable: {exc}"
                ) from exc
            yield
        finally:
            if lock_fd is not None:
                try:
                    if acquired:
                        self._release_advisory_lock(lock_fd)
                except OSError as exc:
                    release_error = BrewPersistenceError(
                        f"Could not release brew session lock for {session_id}: {exc}"
                    )
                finally:
                    try:
                        os.close(lock_fd)
                    except OSError as exc:
                        if release_error is None:
                            release_error = BrewPersistenceError(
                                f"Could not close brew session lock for {session_id}: {exc}"
                            )
                if release_error is not None:
                    raise release_error

    @staticmethod
    def _acquire_advisory_lock(lock_fd: int) -> None:
        if os.name == "nt":
            if os.fstat(lock_fd).st_size == 0:
                os.write(lock_fd, b"\0")
            os.lseek(lock_fd, 0, os.SEEK_SET)
            msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _release_advisory_lock(lock_fd: int) -> None:
        if os.name == "nt":
            os.lseek(lock_fd, 0, os.SEEK_SET)
            msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)

    @staticmethod
    def _validate_session_id(session_id: str) -> None:
        if not isinstance(session_id, str) or not _SESSION_ID_PATTERN.fullmatch(session_id):
            raise ValueError(
                "Invalid session ID: use 1-80 filename-safe letters, digits, '.', '_', or '-'; "
                "the first character must be alphanumeric"
            )

    def _target_for(self, session_id: str) -> Path:
        self._validate_session_id(session_id)
        target = (self.root / f"{session_id}.json").resolve()
        if target.parent != self.root:
            raise ValueError(f"Session ID resolves outside the session store: {session_id}")
        return target

    @staticmethod
    def _validate_session(session: BrewSession) -> None:
        revisions = session.revisions
        revision_numbers = [revision.revision for revision in revisions]
        expected_numbers = list(range(len(revisions)))
        if revision_numbers != expected_numbers:
            raise ValueError("Session revisions must be unique and contiguous starting at 0")

        revision_set = set(revision_numbers)
        for revision in revisions:
            if revision.revision == 0:
                if revision.parent_revision is not None:
                    raise ValueError("Revision 0 parent revision must be null")
            elif (
                not isinstance(revision.parent_revision, int)
                or isinstance(revision.parent_revision, bool)
                or revision.parent_revision < 0
                or revision.parent_revision >= revision.revision
            ):
                raise ValueError(
                    f"Revision {revision.revision} parent revision must precede it: "
                    f"{revision.parent_revision}"
                )
            for zone in (
                "main_deck",
                "sideboard",
                "reservations",
                "rejected_cards",
            ):
                for index, card in enumerate(getattr(revision, zone)):
                    _validate_card_identifier(
                        card,
                        f"Revision {revision.revision} {zone} card {index}",
                    )
        if session.current_revision not in revision_set:
            raise ValueError(
                f"current_revision does not exist: {session.current_revision}"
            )
        if session.current_revision != revisions[-1].revision:
            raise ValueError("current_revision must identify the latest immutable revision")

        for index, card in enumerate(session.leader_cards):
            _validate_card_identifier(card, f"Leader card {index}")
        _validate_card_identifier(session.base_card, "Base card")

        if (session.collection_path is None) != (session.collection_snapshot_hash is None):
            raise ValueError(
                "collection_path and collection_snapshot_hash must either both be set or both be null"
            )
        if session.collection_snapshot_hash is not None:
            _validate_sha256(
                session.collection_snapshot_hash,
                "collection_snapshot_hash",
                allow_absent=True,
            )

        decision_ids = [decision.decision_id for decision in session.decisions]
        if any(not decision_id for decision_id in decision_ids):
            raise ValueError("Brew decision IDs must be nonempty")
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("Brew decision IDs must be unique")
        resulting_revisions: list[int] = []
        for decision in session.decisions:
            if decision.parent_revision not in revision_set:
                raise ValueError(
                    f"Decision {decision.decision_id} references a missing parent revision"
                )
            if decision.resulting_revision not in revision_set:
                raise ValueError(
                    f"Decision {decision.decision_id} references a missing resulting revision"
                )
            resulting = revisions[decision.resulting_revision]
            if decision.resulting_revision == 0:
                raise ValueError(
                    f"Decision {decision.decision_id} cannot produce the initial revision"
                )
            if resulting.parent_revision != decision.parent_revision:
                raise ValueError(
                    f"Decision {decision.decision_id} parent does not match its resulting revision"
                )
            resulting_revisions.append(decision.resulting_revision)
            decision_card_groups = {
                "additions": decision.additions,
                "cuts": decision.cuts,
                "reservations": decision.reservations or [],
                "rejected_cards": decision.rejected_cards or [],
            }
            for group, cards in decision_card_groups.items():
                for index, card in enumerate(cards):
                    _validate_card_identifier(
                        card,
                        f"Decision {decision.decision_id} {group} card {index}",
                    )
        if resulting_revisions != list(range(1, len(revisions))):
            raise ValueError(
                "Each noninitial revision must have exactly one matching brew decision in order"
            )

        for report in session.reports:
            if report.revision not in revision_set:
                raise ValueError(
                    f"Report {report.report_id} references a missing revision"
                )
        report_ids = [report.report_id for report in session.reports]
        if any(not report_id for report_id in report_ids):
            raise ValueError("Brew report IDs must be nonempty")
        if len(report_ids) != len(set(report_ids)):
            raise ValueError("Brew report IDs must be unique")
        reports_by_id = {report.report_id: report for report in session.reports}
        for decision in session.decisions:
            if decision.advisory_report_id is None:
                if decision.accepted_stale_evidence:
                    raise ValueError(
                        f"Decision {decision.decision_id} accepts stale evidence without a report"
                    )
                continue
            report = reports_by_id.get(decision.advisory_report_id)
            if report is None:
                raise ValueError(
                    f"Decision {decision.decision_id} references an unknown advisory report"
                )
            is_stale = report.revision != decision.parent_revision
            if decision.accepted_stale_evidence != is_stale:
                raise ValueError(
                    f"Decision {decision.decision_id} stale-report provenance is inconsistent"
                )

        previous_refresh_hash: str | None = None
        previous_refresh_revision = 0
        validated_refreshes: list[tuple[int, str]] = []
        for index, refresh in enumerate(session.collection_refreshes):
            if not isinstance(refresh, dict):
                raise ValueError(f"Collection refresh {index} must be an object")
            old_hash = _validate_sha256(
                refresh.get("old_hash"),
                f"Collection refresh {index} old_hash",
                allow_absent=True,
            )
            new_hash = _validate_sha256(
                refresh.get("new_hash"),
                f"Collection refresh {index} new_hash",
                allow_absent=True,
            )
            revision = refresh.get("revision")
            if revision not in revision_set or revision == 0:
                raise ValueError(
                    f"Collection refresh {index} references an invalid revision"
                )
            if revision <= previous_refresh_revision:
                raise ValueError("Collection refresh revisions must be strictly ordered")
            if previous_refresh_hash is not None and old_hash != previous_refresh_hash:
                raise ValueError("Collection refresh hashes must form an ordered chain")
            previous_refresh_hash = new_hash
            previous_refresh_revision = revision
            validated_refreshes.append((revision, new_hash))
        if (
            previous_refresh_hash is not None
            and previous_refresh_hash != session.collection_snapshot_hash
        ):
            raise ValueError(
                "The final collection refresh hash must match collection_snapshot_hash"
            )

        receipt_ids: list[str] = []
        serialized_decisions = [
            decision.model_dump(mode="json") for decision in session.decisions
        ]
        initial_collection_hash = (
            session.collection_refreshes[0]["old_hash"]
            if session.collection_refreshes
            else session.collection_snapshot_hash
        )
        for index, receipt in enumerate(session.finalization_receipts):
            if not isinstance(receipt, dict):
                raise ValueError(f"Finalization receipt {index} must be an object")
            receipt_id = receipt.get("receipt_id")
            if not isinstance(receipt_id, str) or not receipt_id:
                raise ValueError(f"Finalization receipt {index} needs a nonempty receipt ID")
            receipt_ids.append(receipt_id)
            revision = receipt.get("revision")
            if (
                not isinstance(revision, int)
                or isinstance(revision, bool)
                or revision not in revision_set
            ):
                raise ValueError(
                    f"Finalization receipt {receipt_id} references a missing revision"
                )
            stored_revision_hash = _validate_sha256(
                receipt.get("finalized_revision_sha256"),
                f"Finalization receipt {receipt_id} revision hash",
            )
            if stored_revision_hash != canonical_revision_hash(revisions[revision]):
                raise ValueError(
                    f"Finalization receipt {receipt_id} revision hash does not match"
                )
            receipt_collection = receipt.get("collection")
            if not isinstance(receipt_collection, dict):
                raise ValueError(
                    f"Finalization receipt {receipt_id} collection must be an object"
                )
            if receipt_collection.get("tracked") is not True:
                raise ValueError(
                    f"Finalization receipt {receipt_id} requires tracked collection provenance"
                )
            if receipt_collection.get("path") != session.collection_path:
                raise ValueError(
                    f"Finalization receipt {receipt_id} collection path is inconsistent"
                )
            receipt_snapshot_hash = _validate_sha256(
                receipt_collection.get("snapshot_hash"),
                f"Finalization receipt {receipt_id} collection snapshot hash",
                allow_absent=True,
            )
            receipt_current_hash = _validate_sha256(
                receipt_collection.get("current_hash"),
                f"Finalization receipt {receipt_id} collection current hash",
                allow_absent=True,
            )
            expected_collection_hash = initial_collection_hash
            for refresh_revision, refresh_hash in validated_refreshes:
                if refresh_revision > revision:
                    break
                expected_collection_hash = refresh_hash
            if (
                expected_collection_hash is None
                or receipt_snapshot_hash != expected_collection_hash
                or receipt_current_hash != expected_collection_hash
                or receipt_collection.get("stale") is not False
            ):
                raise ValueError(
                    f"Finalization receipt {receipt_id} collection provenance is inconsistent"
                )
            for field in ("validation", "analysis"):
                if not isinstance(receipt.get(field), dict):
                    raise ValueError(
                        f"Finalization receipt {receipt_id} {field} must be an object"
                    )
            export_hashes = receipt.get("export_hashes")
            if not isinstance(export_hashes, dict):
                raise ValueError(
                    f"Finalization receipt {receipt_id} export_hashes must be an object"
                )
            for field in ("plain_text_sha256", "holoscan_sha256"):
                _validate_sha256(
                    export_hashes.get(field),
                    f"Finalization receipt {receipt_id} {field}",
                )
            current_report_id = receipt.get("current_advisory_report")
            if current_report_id is not None:
                current_report = reports_by_id.get(current_report_id)
                if current_report is None or current_report.revision != revision:
                    raise ValueError(
                        f"Finalization receipt {receipt_id} current report is inconsistent"
                    )
            stale_report_ids = receipt.get("stale_advisory_reports", [])
            if (
                not isinstance(stale_report_ids, list)
                or any(not isinstance(report_id, str) for report_id in stale_report_ids)
                or len(stale_report_ids) != len(set(stale_report_ids))
            ):
                raise ValueError(
                    f"Finalization receipt {receipt_id} stale reports must be unique IDs"
                )
            for report_id in stale_report_ids:
                report = reports_by_id.get(report_id)
                if report is None or report.revision == revision:
                    raise ValueError(
                        f"Finalization receipt {receipt_id} stale report is inconsistent"
                    )
            decision_history = receipt.get("decision_history")
            expected_decision_history = serialized_decisions[:revision]
            if decision_history != expected_decision_history:
                raise ValueError(
                    f"Finalization receipt {receipt_id} decision history is inconsistent"
                )
        if len(receipt_ids) != len(set(receipt_ids)):
            raise ValueError("Finalization receipt IDs must be unique")

    @staticmethod
    def _validate_append_only_history(
        previous: BrewSession, current: BrewSession
    ) -> None:
        if current.revisions[: len(previous.revisions)] != previous.revisions:
            raise ValueError("Existing brew revisions are immutable")
        if current.decisions[: len(previous.decisions)] != previous.decisions:
            raise ValueError("Brew decisions are append-only")
        if current.reports[: len(previous.reports)] != previous.reports:
            raise ValueError("Brew reports are append-only")
        if (
            current.finalization_receipts[: len(previous.finalization_receipts)]
            != previous.finalization_receipts
        ):
            raise ValueError("Finalization receipts are append-only")
