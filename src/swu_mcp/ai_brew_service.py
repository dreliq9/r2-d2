"""Read-only planning and evidence service for durable AI brew sessions."""

from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from .ai_brew_session import (
    BrewDecision,
    BrewPersistenceError,
    BrewReport,
    BrewRevision,
    BrewSession,
    BrewSessionStore,
    canonical_revision_hash,
    generate_session_id,
)
from .brew_math import (
    mulligan_adjusted,
    pareto_analysis,
    probability_at_least_one,
    probability_enabler_and_payoff,
    seeded_draw_simulation,
    wilson_interval,
)
from .card_identity import canonical_key
from .card_roles import roles_for_card
from .card_service import CardService
from .collection_service import CollectionService, CollectionSnapshot
from .deck_service import (
    PREMIER,
    PREMIER_LEADER_COUNT,
    PREMIER_MAIN_DECK_MIN,
    PREMIER_SIDEBOARD_MAX,
    STARTING_HAND_SIZE,
    TWIN_SUNS,
    TWIN_SUNS_LEADER_COUNT,
    TWIN_SUNS_MAIN_DECK_MIN,
    DeckService,
    card_copy_override,
    normalize_format,
    parse_int,
    shared_alignment,
)
from .deck_thesis import build_deck_thesis
from .interaction_glossary import needs_set, provides_set
from .types import (
    MAX_BREW_CANDIDATE_SWAPS,
    MAX_BREW_CATEGORY_PRINTING_IDS,
    MAX_BREW_MULLIGAN_REDRAWS,
    MAX_BREW_PROBABILITY_CATEGORIES,
    MAX_BREW_SIMULATION_COUNT,
    MAX_BREW_SWAP_CARD_CHANGES,
    MAX_BREW_TURN_HORIZON,
    MAX_BREW_TURN_HORIZONS,
)


_CANDIDATE_INTENTS = {"candidates", "card-candidates"}


class BrewResolutionError(ValueError):
    def __init__(self, message: str, *, candidates: list[dict[str, str]] | None = None) -> None:
        super().__init__(message)
        self.candidates = candidates or []


class BrewCollectionConflictError(ValueError):
    def __init__(self, conflicts: list[dict[str, Any]]) -> None:
        super().__init__("Current collection ownership conflicts with the prospective revision.")
        self.conflicts = conflicts


class AIBrewService:
    def __init__(
        self,
        card_service: CardService,
        collection_service: CollectionService,
        deck_service: DeckService,
        store: BrewSessionStore,
    ) -> None:
        self.card_service = card_service
        self.collection_service = collection_service
        self.deck_service = deck_service
        self.store = store

    def start_brew(
        self,
        *,
        format_name: str,
        leader_names: list[str],
        base_name: str,
        theme: str,
        only_owned: bool = False,
        allow_off_aspect: bool = False,
        target_matchups: list[str] | None = None,
        meta_context: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        session: BrewSession | None = None
        try:
            normalized_format = normalize_format(format_name)
            collection_snapshot = self._collection_snapshot()
            leaders, base = self._resolve_setup(
                format_name=normalized_format,
                leader_names=leader_names,
                base_name=base_name,
                only_owned=only_owned,
                collection_snapshot=collection_snapshot,
            )
            created_at = _now()
            collection_path = str(collection_snapshot.storage_path)
            snapshot_hash = collection_snapshot.sha256
            session = BrewSession(
                session_id=session_id or generate_session_id(),
                created_at=created_at,
                updated_at=created_at,
                format_name=normalized_format,
                stage="planning",
                leader_cards=leaders,
                base_card=base,
                legal_aspects=sorted(
                    {
                        aspect
                        for card in [*leaders, base]
                        for aspect in (card.get("aspects") or card.get("Aspects") or [])
                    }
                ),
                only_owned=only_owned,
                allow_off_aspect=allow_off_aspect,
                collection_path=collection_path,
                collection_snapshot_hash=snapshot_hash,
                theme=theme,
                target_matchups=list(target_matchups or []),
                meta_context=dict(meta_context or {}),
                revisions=[BrewRevision(revision=0, parent_revision=None, created_at=created_at)],
                current_revision=0,
            )
            self.store.create(session)
            return self._success(
                session,
                next_steps=[
                    "Call swu_get_brew_context to inspect factual card evidence.",
                    "Call swu_record_brew_decisions to persist explicit caller choices.",
                ],
                format_name=session.format_name,
                leaders=leaders,
                base=base,
                legal_aspects=session.legal_aspects,
                format_constraints=self._format_constraints(session.format_name),
                collection_snapshot=(
                    {"path": collection_path, "sha256": snapshot_hash}
                    if collection_path is not None and snapshot_hash is not None
                    else None
                ),
            )
        except (ValueError, TypeError, RuntimeError, BrewPersistenceError, OSError) as exc:
            return self._error(
                exc,
                "Correct the setup details and start a new brew session.",
                session=session,
                session_id=session_id,
            )

    def get_context(
        self,
        *,
        session_id: str,
        intent: str,
        filters: dict[str, Any] | None = None,
        cursor: str | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        session: BrewSession | None = None
        try:
            session = self.store.load(session_id)
            normalized_intent = intent.strip().lower()
            collection_snapshot = self._collection_snapshot()
            collection = self._collection_state(session, collection_snapshot)
            diagnostics = self._collection_diagnostics(collection)
            if normalized_intent == "session-summary":
                return self._success(
                    session,
                    diagnostics=diagnostics,
                    next_steps=["Request candidates or revision-history for more brew evidence."],
                    session=self._session_summary(session),
                    collection=collection,
                )
            if normalized_intent == "revision-history":
                return self._success(
                    session,
                    diagnostics=diagnostics,
                    next_steps=["Record a new decision or restore a historical revision explicitly."],
                    revisions=[revision.model_dump(mode="json") for revision in session.revisions],
                    current_revision=session.current_revision,
                    collection=collection,
                )
            if normalized_intent not in _CANDIDATE_INTENTS:
                raise ValueError(
                    "Unsupported context intent. Use candidates, session-summary, or revision-history."
                )
            normalized_filters = _normalize_context_filters(filters)
            return self._candidate_context(
                session=session,
                intent=normalized_intent,
                filters=normalized_filters,
                cursor=cursor,
                limit=limit,
                collection=collection,
                collection_snapshot=collection_snapshot,
            )
        except (ValueError, TypeError, BrewPersistenceError, OSError, json.JSONDecodeError) as exc:
            return self._error(
                exc,
                "Check the session ID, intent, filters, and cursor before retrying.",
                session=session,
                session_id=session_id,
            )

    def record_decisions(
        self,
        *,
        session_id: str,
        expected_revision: int,
        thesis: str | None = None,
        packages: list[dict[str, Any]] | None = None,
        role_targets: dict[str, int] | None = None,
        additions: list[dict[str, Any]] | None = None,
        cuts: list[dict[str, Any]] | None = None,
        reservations: list[dict[str, Any]] | None = None,
        rejected_cards: list[dict[str, Any]] | None = None,
        rationale: str = "",
        evidence_ids: list[str] | None = None,
        advisory_report_id: str | None = None,
        accept_stale_evidence: bool = False,
        restore_revision: int | None = None,
        refresh_collection: bool = False,
    ) -> dict[str, Any]:
        """Append one validated, immutable revision from explicit caller decisions."""

        session: BrewSession | None = None
        collection: dict[str, Any] | None = None
        collection_snapshot: CollectionSnapshot | None = None
        try:
            session = self.store.load(session_id)
            rationale = self._require_text(rationale, "rationale")
            if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
                raise ValueError("expected_revision must be an integer.")
            if expected_revision != session.current_revision:
                raise ValueError(
                    f"expected revision {expected_revision}, but current revision is {session.current_revision}."
                )
            if restore_revision is not None:
                if not isinstance(restore_revision, int) or isinstance(restore_revision, bool):
                    raise ValueError("restore_revision must be an integer.")
                if restore_revision < 0 or restore_revision >= len(session.revisions):
                    raise ValueError(f"Cannot restore missing revision {restore_revision}.")
            parent_revision = (
                restore_revision if restore_revision is not None else session.current_revision
            )
            self._validate_advisory_report(
                session,
                advisory_report_id,
                parent_revision,
                accept_stale_evidence=accept_stale_evidence,
            )

            collection_snapshot = self._collection_snapshot()
            collection = self._collection_state(session, collection_snapshot)
            if collection["stale"]:
                collection = {
                    "tracked": True,
                    "stale": True,
                    "old_hash": session.collection_snapshot_hash,
                    "new_hash": collection["current_hash"],
                }
                if not refresh_collection:
                    raise ValueError(
                        "Collection changed since this brew started: "
                        f"old hash {collection['old_hash']}, new hash {collection['new_hash']}."
                    )

            working = deepcopy(session)
            parent = working.revisions[parent_revision]
            resolved_additions = self._resolve_decision_cards(additions or [])
            resolved_cuts = self._resolve_decision_cards(cuts or [])
            resolved_reservations = self._resolve_decision_cards(reservations or [])
            resolved_rejections = self._resolve_decision_cards(rejected_cards or [])
            main_additions, sideboard_additions = _partition_decision_cards(resolved_additions)
            main_cuts, sideboard_cuts = _partition_decision_cards(resolved_cuts)
            prospective_main_deck = self._apply_deck_changes(
                parent.main_deck,
                additions=main_additions,
                cuts=main_cuts,
            )
            prospective_sideboard = self._apply_deck_changes(
                parent.sideboard,
                additions=sideboard_additions,
                cuts=sideboard_cuts,
            )
            prospective_revision = BrewRevision(
                revision=len(working.revisions),
                parent_revision=parent_revision,
                created_at=_now(),
                thesis=parent.thesis if thesis is None else self._require_text(thesis, "thesis"),
                packages=deepcopy(parent.packages if packages is None else self._require_dict_list(packages, "packages")),
                role_targets=deepcopy(
                    parent.role_targets if role_targets is None else self._require_role_targets(role_targets)
                ),
                main_deck=prospective_main_deck,
                sideboard=prospective_sideboard,
                reservations=deepcopy(
                    parent.reservations if reservations is None else resolved_reservations
                ),
                rejected_cards=deepcopy(
                    parent.rejected_cards if rejected_cards is None else resolved_rejections
                ),
            )
            if self._is_substantive_change(
                parent=parent,
                revision=prospective_revision,
                additions=resolved_additions,
                cuts=resolved_cuts,
                restore_revision=restore_revision,
            ) and not rationale.strip():
                raise ValueError("A rationale is required for a substantive decision.")

            self._validate_setup_ownership(working, collection_snapshot)
            self._validate_prospective_revision(
                working,
                prospective_revision,
                collection_snapshot=collection_snapshot,
            )

            working.revisions.append(prospective_revision)
            working.decisions.append(
                BrewDecision(
                    decision_id=uuid4().hex,
                    parent_revision=parent_revision,
                    resulting_revision=prospective_revision.revision,
                    additions=deepcopy(resolved_additions),
                    cuts=deepcopy(resolved_cuts),
                    thesis=thesis,
                    packages=deepcopy(packages),
                    role_targets=deepcopy(role_targets),
                    reservations=deepcopy(resolved_reservations if reservations is not None else None),
                    rejected_cards=deepcopy(
                        resolved_rejections if rejected_cards is not None else None
                    ),
                    rationale=rationale.strip(),
                    evidence_ids=self._require_string_list(evidence_ids or [], "evidence_ids"),
                    advisory_report_id=advisory_report_id,
                    accepted_stale_evidence=accept_stale_evidence,
                    created_at=prospective_revision.created_at,
                )
            )
            working.current_revision = prospective_revision.revision
            working.updated_at = prospective_revision.created_at
            working.stage = "drafting" if session.stage == "planning" else "revising"
            if collection is not None and collection["stale"]:
                working.collection_snapshot_hash = str(collection["new_hash"])
                working.collection_refreshes.append(
                    {
                        "old_hash": collection["old_hash"],
                        "new_hash": collection["new_hash"],
                        "revision": prospective_revision.revision,
                        "created_at": prospective_revision.created_at,
                    }
                )

            current_collection_snapshot = self._collection_snapshot()
            if current_collection_snapshot.sha256 != collection_snapshot.sha256:
                raise ValueError(
                    "Collection changed during decision validation: "
                    f"validated hash {collection_snapshot.sha256}, current hash "
                    f"{current_collection_snapshot.sha256}."
                )
            self.store.save(working)
            return self._success(
                working,
                next_steps=[
                    "Evaluate the new revision or record another explicit decision group."
                ],
                parent_revision=parent_revision,
                decision_id=working.decisions[-1].decision_id,
                collection=self._collection_state(working, collection_snapshot),
            )
        except BrewCollectionConflictError as exc:
            return self._decision_error(
                exc,
                collection={**(collection or {}), "conflicts": exc.conflicts},
                session=session,
                session_id=session_id,
            )
        except (ValueError, TypeError, RuntimeError, BrewPersistenceError, OSError, json.JSONDecodeError) as exc:
            return self._decision_error(
                exc,
                collection=collection,
                session=session,
                session_id=session_id,
            )

    def evaluate_brew(
        self,
        *,
        session_id: str,
        revision: int | None = None,
        turn_horizons: list[int] | None = None,
        mulligan_redraws: int = 1,
        simulation_seed: int = 1,
        simulation_count: int = 1000,
        matchup_inputs: dict[str, Any] | None = None,
        probability_categories: list[dict[str, Any]] | None = None,
        candidate_swaps: list[dict[str, Any]] | None = None,
        objective_directions: dict[str, Literal["min", "max"]] | None = None,
    ) -> dict[str, Any]:
        """Persist an advisory-only evaluation bound to one immutable revision."""

        session: BrewSession | None = None
        try:
            session = self.store.load(session_id)
            evaluation_revision = self._evaluation_revision(session, revision)
            horizons = self._turn_horizons(turn_horizons)
            self._require_nonnegative_int("mulligan_redraws", mulligan_redraws)
            if mulligan_redraws > MAX_BREW_MULLIGAN_REDRAWS:
                raise ValueError(
                    f"mulligan_redraws must be at most {MAX_BREW_MULLIGAN_REDRAWS}."
                )
            self._require_int("simulation_seed", simulation_seed)
            self._require_int("simulation_count", simulation_count)
            if simulation_count < 1:
                raise ValueError("simulation_count must be at least 1.")
            if simulation_count > MAX_BREW_SIMULATION_COUNT:
                raise ValueError(
                    f"simulation_count must be at most {MAX_BREW_SIMULATION_COUNT}."
                )
            if matchup_inputs is not None and not isinstance(matchup_inputs, dict):
                raise ValueError("matchup_inputs must be an object.")

            candidate_swaps = self._validated_candidate_swaps(candidate_swaps)
            categories = self._probability_categories(probability_categories)
            target = session.revisions[evaluation_revision]
            collection_snapshot = self._collection_snapshot()
            collection = self._collection_state(session, collection_snapshot)
            stale_ownership_limitation = (
                "Only-owned collection provenance is stale; candidate ownership-dependent "
                "comparison and Pareto classification are unavailable."
                if session.only_owned and collection["stale"]
                else None
            )
            content, probability_values = self._evaluate_revision_content(
                session=session,
                revision=target,
                horizons=horizons,
                mulligan_redraws=mulligan_redraws,
                simulation_seed=simulation_seed,
                simulation_count=simulation_count,
                matchup_inputs=matchup_inputs or {},
                probability_categories=categories,
                include_goldfish=True,
            )
            swaps = self._evaluate_candidate_swaps(
                session=session,
                revision=target,
                horizons=horizons,
                mulligan_redraws=mulligan_redraws,
                matchup_inputs=matchup_inputs or {},
                probability_categories=categories,
                candidate_swaps=candidate_swaps,
                collection_snapshot=collection_snapshot,
                base_objectives=content["objective_vector"],
                base_probability_values=probability_values,
                objective_directions=objective_directions,
                unavailable_reason=stale_ownership_limitation,
            )
            content["candidate_swaps"] = swaps
            content["collection"] = deepcopy(collection)
            if stale_ownership_limitation is not None:
                content["limitations"].append(stale_ownership_limitation)

            created_at = _now()
            report_id = uuid4().hex
            working = deepcopy(session)
            working.reports.append(
                BrewReport(
                    report_id=report_id,
                    revision=evaluation_revision,
                    created_at=created_at,
                    inputs={
                        "turn_horizons": horizons,
                        "mulligan_redraws": mulligan_redraws,
                        "simulation_seed": simulation_seed,
                        "simulation_count": simulation_count,
                        "matchup_inputs": deepcopy(matchup_inputs or {}),
                        "probability_categories": deepcopy(probability_categories or []),
                        "candidate_swaps": deepcopy(candidate_swaps or []),
                        "objective_directions": deepcopy(objective_directions),
                    },
                    result=deepcopy(content),
                )
            )
            if evaluation_revision == session.current_revision:
                working.stage = "evaluating"
                working.updated_at = created_at
            self.store.save(working)
            return self._success(
                working,
                revision=evaluation_revision,
                diagnostics=self._collection_diagnostics(collection),
                next_steps=[
                    "Record any accepted or rejected suggestion explicitly against this report."
                ],
                report_id=report_id,
                **content,
            )
        except (ValueError, TypeError, RuntimeError, BrewPersistenceError, OSError, json.JSONDecodeError) as exc:
            return self._error(
                exc,
                "Check the session, revision, and advisory evaluation inputs before retrying.",
                session=session,
                session_id=session_id,
            )

    def finalize_brew(self, *, session_id: str, expected_revision: int) -> dict[str, Any]:
        """Persist one immutable receipt after all final deck gates pass."""

        session: BrewSession | None = None
        collection: dict[str, Any] | None = None
        try:
            session = self.store.load(session_id)
            if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
                raise ValueError("expected_revision must be an integer.")
            if expected_revision != session.current_revision:
                raise ValueError(
                    f"expected revision {expected_revision}, but current revision is "
                    f"{session.current_revision}."
                )

            collection_snapshot = self._collection_snapshot()
            collection = self._collection_state(session, collection_snapshot)
            if not collection["tracked"]:
                raise ValueError("Finalization requires tracked collection provenance.")
            if collection["stale"]:
                raise ValueError(
                    "Collection changed since this brew started: "
                    f"snapshot hash {session.collection_snapshot_hash}, "
                    f"current hash {collection['current_hash']}."
                )

            finalization_session, revision = self._finalization_snapshot(
                session,
                session.revisions[session.current_revision],
            )
            self._validate_setup_ownership(finalization_session, collection_snapshot)
            self._validate_prospective_revision(
                finalization_session,
                revision,
                collection_snapshot=collection_snapshot,
            )
            deck = self._revision_deck(finalization_session, revision)
            validation = self.deck_service.validate_deck(
                decklist=deck,
                format_name=finalization_session.format_name,
            )
            self._validate_finalization_structure(finalization_session, validation)
            if not validation["legal"]:
                errors = validation.get("errors", [])
                raise ValueError(
                    "Deck validation failed: " + "; ".join(str(error) for error in errors)
                )

            analysis = self.deck_service.analyze_deck(
                decklist=deck,
                format_name=finalization_session.format_name,
                target_matchups=finalization_session.target_matchups,
                meta_context=finalization_session.meta_context,
            )
            plain_text = self.deck_service.export_deck(
                decklist=deck,
                format_name=finalization_session.format_name,
                export_format="plain_text",
            )
            holoscan = self.deck_service.export_deck(
                decklist=deck,
                format_name=finalization_session.format_name,
                export_format="holoscan",
            )
            self._validate_holoscan_round_trip(
                deck=deck,
                holoscan=str(holoscan["deck"]),
                format_name=finalization_session.format_name,
            )

            current_reports = [
                report for report in session.reports if report.revision == session.current_revision
            ]
            current_report_id = current_reports[-1].report_id if current_reports else None
            latest_mathematical_report = (
                deepcopy(current_reports[-1].result) if current_reports else None
            )
            stale_report_ids = [
                report.report_id for report in session.reports if report.revision != session.current_revision
            ]
            decision_history = [
                decision.model_dump(mode="json") for decision in session.decisions
            ]
            finalized_at = _now()
            receipt = {
                "receipt_id": uuid4().hex,
                "finalized_at": finalized_at,
                "revision": session.current_revision,
                "finalized_revision_sha256": canonical_revision_hash(
                    session.revisions[session.current_revision]
                ),
                "collection": deepcopy(collection),
                "validation": deepcopy(validation),
                "analysis": deepcopy(analysis),
                "export_hashes": {
                    "plain_text_sha256": hashlib.sha256(
                        str(plain_text["deck"]).encode("utf-8")
                    ).hexdigest(),
                    "holoscan_sha256": hashlib.sha256(
                        str(holoscan["deck"]).encode("utf-8")
                    ).hexdigest(),
                },
                "current_advisory_report": current_report_id,
                "stale_advisory_reports": stale_report_ids,
                "decision_history": deepcopy(decision_history),
            }

            working = deepcopy(session)
            working.finalization_receipts.append(receipt)
            working.stage = "finalized"
            working.updated_at = finalized_at
            final_collection_snapshot = self._collection_snapshot()
            if final_collection_snapshot.sha256 != collection_snapshot.sha256:
                raise ValueError("Collection changed during finalization; retry with current collection provenance.")
            self.store.save(working)
            return self._success(
                working,
                next_steps=["Use the returned exports and immutable receipt as the finalized deck record."],
                collection=collection,
                validation=validation,
                analysis=analysis,
                plain_text=plain_text,
                holoscan=holoscan,
                latest_mathematical_report=latest_mathematical_report,
                advisory_reports={
                    "current": current_report_id,
                    "stale": stale_report_ids,
                },
                decision_history=decision_history,
                receipt=receipt,
            )
        except (
            KeyError,
            ValueError,
            TypeError,
            RuntimeError,
            BrewPersistenceError,
            OSError,
            json.JSONDecodeError,
        ) as exc:
            result = self._error(
                exc,
                "Correct the current revision, collection provenance, or deck legality before finalizing.",
                session=session,
                session_id=session_id,
            )
            if collection is not None:
                result["collection"] = collection
            return result

    @staticmethod
    def _validate_finalization_structure(
        session: BrewSession, validation: dict[str, Any]
    ) -> None:
        counts = validation.get("counts")
        if not isinstance(counts, dict):
            raise ValueError("Deck validation did not return structural counts.")
        leaders = counts.get("leaders")
        bases = counts.get("bases")
        main_deck = counts.get("main_deck")
        if session.format_name == PREMIER:
            if leaders != PREMIER_LEADER_COUNT:
                raise ValueError("Premier requires exactly one leader for finalization.")
            if bases != 1:
                raise ValueError("Premier requires exactly one base for finalization.")
            if not isinstance(main_deck, int) or main_deck < PREMIER_MAIN_DECK_MIN:
                raise ValueError(
                    f"Premier requires at least {PREMIER_MAIN_DECK_MIN} main-deck cards for finalization."
                )
            return
        if leaders != TWIN_SUNS_LEADER_COUNT:
            raise ValueError("Twin Suns requires exactly two leaders for finalization.")
        if bases != 1:
            raise ValueError("Twin Suns requires exactly one base for finalization.")
        if main_deck != TWIN_SUNS_MAIN_DECK_MIN:
            raise ValueError(
                f"Twin Suns requires exactly {TWIN_SUNS_MAIN_DECK_MIN} main-deck cards for finalization."
            )

    def _finalization_snapshot(
        self, session: BrewSession, revision: BrewRevision
    ) -> tuple[BrewSession, BrewRevision]:
        """Resolve every persisted printing before it can influence a final receipt."""

        snapshot = deepcopy(session)

        def resolve_card(card: dict[str, Any], *, zone: str) -> dict[str, Any]:
            resolved = self._resolve_exact_printing({"printing_id": self._printing_id(card)})
            if zone == "leaders" and resolved.get("card_type") != "Leader":
                raise ValueError("A finalized brew leader must resolve to a Leader card.")
            if zone == "bases" and resolved.get("card_type") != "Base":
                raise ValueError("A finalized brew base must resolve to a Base card.")
            return resolved

        snapshot.leader_cards = [resolve_card(card, zone="leaders") for card in session.leader_cards]
        snapshot.base_card = resolve_card(session.base_card, zone="bases")
        snapshot_revision = snapshot.revisions[session.current_revision]
        snapshot_revision.main_deck = [
            {
                **resolve_card(card, zone="main_deck"),
                "quantity": self._decision_quantity(card),
            }
            for card in revision.main_deck
        ]
        snapshot_revision.sideboard = [
            {
                **resolve_card(card, zone="sideboard"),
                "quantity": self._decision_quantity(card),
            }
            for card in revision.sideboard
        ]
        expected_aspects = sorted(
            {
                aspect
                for card in [*snapshot.leader_cards, snapshot.base_card]
                for aspect in (card.get("aspects") or card.get("Aspects") or [])
            }
        )
        if snapshot.legal_aspects != expected_aspects:
            raise ValueError("Stored legal aspects do not match the exact finalized leaders and base.")
        return snapshot, snapshot_revision

    def _validate_setup_ownership(
        self,
        session: BrewSession,
        collection_snapshot: CollectionSnapshot,
    ) -> None:
        if not session.only_owned:
            return
        conflicts: list[dict[str, Any]] = []
        for card in [*session.leader_cards, session.base_card]:
            owned, _ = self._canonical_ownership(card, collection_snapshot)
            if owned < 1:
                conflicts.append(
                    {
                        "printing_id": self._printing_id(card),
                        "requested": 1,
                        "owned": owned,
                    }
                )
        if conflicts:
            raise BrewCollectionConflictError(conflicts)

    def _validate_holoscan_round_trip(
        self,
        *,
        deck: dict[str, Any],
        holoscan: str,
        format_name: str,
    ) -> None:
        round_tripped = self.deck_service.resolve_deck(
            self.deck_service.parse_decklist(decklist=holoscan, format_name=format_name)
        )
        expected = {
            "leaders": sorted(
                (f"{entry['set_code']}/{entry['card_number']}", entry["quantity"])
                for entry in deck["leaders"]
            ),
            "bases": sorted(
                (f"{entry['set_code']}/{entry['card_number']}", entry["quantity"])
                for entry in deck["bases"]
            ),
            "main_deck": sorted(
                (f"{entry['set_code']}/{entry['card_number']}", entry["quantity"])
                for entry in deck["main_deck"]
            ),
            "sideboard": sorted(
                (f"{entry['set_code']}/{entry['card_number']}", entry["quantity"])
                for entry in deck["sideboard"]
            ),
        }
        actual = {
            "leaders": sorted((str(entry.lookup_id), entry.quantity) for entry in round_tripped.leaders),
            "bases": sorted((str(entry.lookup_id), entry.quantity) for entry in round_tripped.bases),
            "main_deck": sorted(
                (str(entry.lookup_id), entry.quantity) for entry in round_tripped.main_deck
            ),
            "sideboard": sorted(
                (str(entry.lookup_id), entry.quantity) for entry in round_tripped.sideboard
            ),
        }
        if actual != expected:
            raise ValueError("Holoscan export did not round-trip through the deck parser and resolver.")

    @staticmethod
    def _evaluation_revision(session: BrewSession, revision: int | None) -> int:
        if revision is None:
            return session.current_revision
        if not isinstance(revision, int) or isinstance(revision, bool):
            raise ValueError("revision must be an integer when provided.")
        if revision < 0 or revision >= len(session.revisions):
            raise ValueError(f"Cannot evaluate missing revision {revision}.")
        return revision

    @staticmethod
    def _turn_horizons(turn_horizons: list[int] | None) -> list[int]:
        horizons = [1, 2, 3] if turn_horizons is None else turn_horizons
        if not isinstance(horizons, list):
            raise ValueError("turn_horizons must be a list of nonnegative integer turns.")
        if len(horizons) > MAX_BREW_TURN_HORIZONS:
            raise ValueError(
                f"turn_horizons may contain at most {MAX_BREW_TURN_HORIZONS} entries."
            )
        if any(not isinstance(turn, int) or isinstance(turn, bool) or turn < 0 for turn in horizons):
            raise ValueError("turn_horizons must be a list of nonnegative integer turns.")
        if any(turn > MAX_BREW_TURN_HORIZON for turn in horizons):
            raise ValueError(
                f"Each turn horizon must be at most {MAX_BREW_TURN_HORIZON}."
            )
        return sorted(set(horizons))

    @staticmethod
    def _require_int(label: str, value: object) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{label} must be an integer.")
        return value

    @classmethod
    def _require_nonnegative_int(cls, label: str, value: object) -> int:
        number = cls._require_int(label, value)
        if number < 0:
            raise ValueError(f"{label} must be nonnegative.")
        return number

    @staticmethod
    def _probability_categories(
        raw_categories: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        if raw_categories is None:
            return []
        if not isinstance(raw_categories, list):
            raise ValueError("probability_categories must be a list of objects.")
        if len(raw_categories) > MAX_BREW_PROBABILITY_CATEGORIES:
            raise ValueError(
                "probability_categories may contain at most "
                f"{MAX_BREW_PROBABILITY_CATEGORIES} entries."
            )
        categories: list[dict[str, Any]] = []
        names: set[str] = set()
        for index, raw in enumerate(raw_categories):
            if not isinstance(raw, dict):
                raise ValueError("Each probability category must be an object.")
            name = raw.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Each probability category needs a nonempty name.")
            if name in names:
                raise ValueError(f"Probability category names must be unique: {name}.")
            names.add(name)
            raw_ids = raw.get(
                "printing_ids",
                raw.get("lookup_ids", raw.get("card_ids", raw.get("cards", []))),
            )
            if not isinstance(raw_ids, list) or not raw_ids:
                raise ValueError(f"Probability category {name} needs a nonempty printing_ids list.")
            if len(raw_ids) > MAX_BREW_CATEGORY_PRINTING_IDS:
                raise ValueError(
                    f"Probability category {name} printing_ids may contain at most "
                    f"{MAX_BREW_CATEGORY_PRINTING_IDS} entries."
                )
            printing_ids: set[str] = set()
            for raw_id in raw_ids:
                if isinstance(raw_id, dict):
                    raw_id = raw_id.get("printing_id") or raw_id.get("lookup_id")
                if not isinstance(raw_id, str) or not raw_id.strip():
                    raise ValueError(f"Probability category {name} has an invalid printing ID.")
                printing_ids.add(raw_id)
            kind = raw.get("kind", raw.get("role"))
            if kind is not None and kind not in {"enabler", "payoff"}:
                raise ValueError(f"Probability category {name} kind must be enabler or payoff.")
            categories.append(
                {
                    "name": name,
                    "printing_ids": printing_ids,
                    "kind": kind,
                    "index": index,
                }
            )
        return categories

    @staticmethod
    def _validated_candidate_swaps(
        candidate_swaps: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        if candidate_swaps is None:
            return None
        if not isinstance(candidate_swaps, list):
            raise ValueError("candidate_swaps must be a list of objects.")
        if len(candidate_swaps) > MAX_BREW_CANDIDATE_SWAPS:
            raise ValueError(
                f"candidate_swaps may contain at most {MAX_BREW_CANDIDATE_SWAPS} entries."
            )
        suggestion_ids: set[str] = set()
        for index, raw_swap in enumerate(candidate_swaps):
            if not isinstance(raw_swap, dict):
                raise ValueError("Each candidate swap must be an object.")
            suggestion_id = raw_swap.get("suggestion_id", f"candidate-{index + 1}")
            if not isinstance(suggestion_id, str) or not suggestion_id.strip():
                raise ValueError("Each candidate swap needs a nonempty suggestion_id.")
            if suggestion_id == "baseline":
                raise ValueError("candidate suggestion_id 'baseline' is reserved.")
            if suggestion_id in suggestion_ids:
                raise ValueError(f"candidate suggestion_id must be unique: {suggestion_id}.")
            suggestion_ids.add(suggestion_id)
            for field in ("adds", "cuts"):
                changes = raw_swap.get(field, [])
                if not isinstance(changes, list):
                    raise ValueError(f"candidate swap {field} must be a list.")
                if len(changes) > MAX_BREW_SWAP_CARD_CHANGES:
                    raise ValueError(
                        f"candidate swap {field} may contain at most "
                        f"{MAX_BREW_SWAP_CARD_CHANGES} entries."
                    )
        return candidate_swaps

    def _evaluate_revision_content(
        self,
        *,
        session: BrewSession,
        revision: BrewRevision,
        horizons: list[int],
        mulligan_redraws: int,
        simulation_seed: int,
        simulation_count: int,
        matchup_inputs: dict[str, Any],
        probability_categories: list[dict[str, Any]],
        include_goldfish: bool,
    ) -> tuple[dict[str, Any], dict[str, float | None]]:
        deck = self._revision_deck(session, revision)
        validation = self.deck_service.validate_deck(
            decklist=deck,
            format_name=session.format_name,
        )
        meta_context = {**deepcopy(session.meta_context), **deepcopy(matchup_inputs)}
        analysis = self.deck_service.analyze_deck(
            decklist=deck,
            format_name=session.format_name,
            target_matchups=session.target_matchups,
            meta_context=meta_context,
        )
        probabilities, simulation, probability_values, probability_limitations = (
            self._probability_evaluation(
                revision=revision,
                deck_size=analysis["deck_size"],
                horizons=horizons,
                mulligan_redraws=mulligan_redraws,
                simulation_seed=simulation_seed,
                simulation_count=simulation_count,
                categories=probability_categories,
            )
        )
        objective_vector, objective_details, objective_limitations = self._objective_vector(
            validation=validation,
            analysis=analysis,
            plan_reliability=probabilities["plan_reliability"],
        )
        limitations = [
            *probability_limitations,
            *objective_limitations,
            (
                "Unsupported mechanics are not modeled: opponent choices, timing windows, "
                "nested optional triggers, and card-specific rules interactions outside DeckService."
            ),
            (
                "Evaluation is advisory only: it does not change revision contents or accept "
                "candidate suggestions."
            ),
        ]
        goldfish: dict[str, Any]
        if include_goldfish and validation["legal"]:
            goldfish = {
                **self.deck_service.goldfish_deck_report(
                    decklist=self._goldfish_decklist(deck),
                    format_name=session.format_name,
                    games=simulation_count,
                    seed=simulation_seed,
                ),
                "available": True,
                "seed": simulation_seed,
            }
        else:
            goldfish = {
                "available": False,
                "limitations": [
                    "Goldfish report is available only for a complete, structurally legal, resolvable deck."
                ],
            }
            if include_goldfish:
                limitations.extend(goldfish["limitations"])

        return (
            {
                "hard_constraints": validation,
                "validation": validation,
                "analysis": analysis,
                "objective_vector": objective_vector,
                "objective_details": objective_details,
                "probabilities": probabilities,
                "simulation": simulation,
                "goldfish": goldfish,
                "limitations": limitations,
            },
            probability_values,
        )

    def _revision_deck(self, session: BrewSession, revision: BrewRevision) -> dict[str, Any]:
        return {
            "leaders": [self._deck_entry(card, 1) for card in session.leader_cards],
            "bases": [self._deck_entry(session.base_card, 1)],
            "main_deck": [
                self._deck_entry(card, self._decision_quantity(card))
                for card in revision.main_deck
            ],
            "sideboard": [
                self._deck_entry(card, self._decision_quantity(card))
                for card in revision.sideboard
            ],
        }

    @staticmethod
    def _deck_entry(card: dict[str, Any], quantity: int) -> dict[str, Any]:
        printing_id = AIBrewService._printing_id(card)
        set_code, card_number = printing_id.split("/", 1)
        return {
            "set_code": set_code,
            "card_number": card_number,
            "quantity": quantity,
        }

    @staticmethod
    def _printing_id(card: dict[str, Any]) -> str:
        printing_id = card.get("lookup_id") or card.get("printing_id")
        if isinstance(printing_id, str) and "/" in printing_id:
            return printing_id
        set_code = card.get("set_code") or card.get("Set") or card.get("set")
        number = card.get("number") or card.get("Number") or card.get("card_number")
        if isinstance(set_code, str) and number is not None:
            return f"{set_code}/{number}"
        raise ValueError("A stored brew card lacks a resolvable exact printing ID.")

    @staticmethod
    def _goldfish_decklist(deck: dict[str, Any]) -> str:
        sections = [
            ("Leaders", deck["leaders"]),
            ("Base", deck["bases"]),
            ("Main Deck", deck["main_deck"]),
            ("Sideboard", deck["sideboard"]),
        ]
        lines: list[str] = []
        for heading, entries in sections:
            if not entries and heading == "Sideboard":
                continue
            if lines:
                lines.append("")
            lines.append(heading)
            lines.extend(
                f"{entry['quantity']} {entry['set_code']}/{entry['card_number']}"
                for entry in entries
            )
        return "\n".join(lines)

    def _probability_evaluation(
        self,
        *,
        revision: BrewRevision,
        deck_size: int,
        horizons: list[int],
        mulligan_redraws: int,
        simulation_seed: int,
        simulation_count: int,
        categories: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, float | None], list[str]]:
        limitations: list[str] = []
        simulation: dict[str, Any] = {
            "seed": simulation_seed,
            "count": simulation_count,
            "hand_size": STARTING_HAND_SIZE,
            "draw_schedule": {
                "opening_hand": STARTING_HAND_SIZE,
                "additional_cards_seen_per_turn": 1,
            },
            "categories": {},
            "limitations": [
                (
                    "Finite-sample Monte Carlo estimates include uncertainty; "
                    "each sampled result includes a 95% Wilson interval."
                ),
                (
                    "Simulation samples category presence only and does not model mulligans, "
                    "card costs, play sequences, opponent choices, or rules interactions."
                ),
            ],
        }
        if not categories:
            simulation["limitations"].append(
                "Simulation is unavailable because no probability categories were supplied."
            )
            limitations.append(
                "Plan reliability is unavailable because no probability categories were supplied."
            )
            return (
                {"categories": [], "enabler_payoff": [], "plan_reliability": None},
                simulation,
                {},
                limitations,
            )
        if deck_size < STARTING_HAND_SIZE:
            simulation["limitations"].append(
                "Simulation is unavailable because the current main deck cannot supply a full opening hand."
            )
            limitations.append(
                "Probability and draw simulation are unavailable until the main deck has a full opening hand."
            )
            return (
                {"categories": [], "enabler_payoff": [], "plan_reliability": None},
                simulation,
                {category["name"]: None for category in categories},
                limitations,
            )
        if any(STARTING_HAND_SIZE + turn > deck_size for turn in horizons):
            raise ValueError("Each requested turn horizon must fit within the current main deck.")

        quantities: dict[str, int] = {}
        for entry in revision.main_deck:
            printing_id = self._printing_id(entry)
            quantities[printing_id] = quantities.get(printing_id, 0) + self._decision_quantity(entry)

        category_reports: list[dict[str, Any]] = []
        probability_values: dict[str, float | None] = {}
        draws_by_turn = {turn: turn for turn in horizons if turn > 0}
        for category in categories:
            name = category["name"]
            successes = sum(quantities.get(card_id, 0) for card_id in category["printing_ids"])
            opening_result = probability_at_least_one(
                population=deck_size,
                successes=successes,
                draws=STARTING_HAND_SIZE,
            )
            by_turn: dict[str, dict[str, Any]] = {}
            for turn in horizons:
                draws = STARTING_HAND_SIZE + turn
                by_turn[str(turn)] = {
                    "draws": draws,
                    "formula": "1 - C(population - successes, draws) / C(population, draws)",
                    "result": probability_at_least_one(
                        population=deck_size,
                        successes=successes,
                        draws=draws,
                    ),
                    "assumptions": [
                        "Cards are drawn uniformly without replacement from the current main deck.",
                        "One additional card is seen per turn after the opening hand.",
                    ],
                }
            category_reports.append(
                {
                    "name": name,
                    "population": deck_size,
                    "successes": successes,
                    "opening_hand": {
                        "draws": STARTING_HAND_SIZE,
                        "formula": "1 - C(population - successes, draws) / C(population, draws)",
                        "result": opening_result,
                        "assumptions": [
                            "Cards are drawn uniformly without replacement from the current main deck.",
                            "One additional card is seen per turn after the opening hand.",
                        ],
                    },
                    "by_turn": by_turn,
                    "mulligan": {
                        "redraws": mulligan_redraws,
                        "method": "independent_full_redraw_approximation",
                        "is_approximation": True,
                        "result": mulligan_adjusted(opening_result, redraws=mulligan_redraws),
                        "assumptions": [
                            "Each redraw is modeled as a fresh full opening hand rather than a partial redraw."
                        ],
                    },
                }
            )
            probability_values[name] = opening_result
            single_category_simulation = seeded_draw_simulation(
                deck_size=deck_size,
                category_counts={name: successes},
                hand_size=STARTING_HAND_SIZE,
                draws_by_turn=draws_by_turn,
                trials=simulation_count,
                seed=simulation_seed,
            )
            turns = {
                turn: turn_result[name]
                for turn, turn_result in single_category_simulation["results"].items()
            }
            for result in turns.values():
                lower, upper = wilson_interval(result["hits"], simulation_count)
                result["wilson_interval"] = {
                    "confidence": 0.95,
                    "lower": lower,
                    "upper": upper,
                }
            simulation["categories"][name] = {
                "population": deck_size,
                "successes": successes,
                "turns": turns,
            }

        paired_categories = self._enabler_payoff_pairs(categories)
        pair_reports: list[dict[str, Any]] = []
        for enabler, payoff in paired_categories:
            enablers = sum(
                quantities.get(card_id, 0) for card_id in enabler["printing_ids"]
            )
            payoffs = sum(quantities.get(card_id, 0) for card_id in payoff["printing_ids"])
            overlap = sum(
                quantities.get(card_id, 0)
                for card_id in enabler["printing_ids"] & payoff["printing_ids"]
            )
            by_turn = {}
            for turn in horizons:
                draws = STARTING_HAND_SIZE + turn
                by_turn[str(turn)] = {
                    "draws": draws,
                    "result": probability_enabler_and_payoff(
                        population=deck_size,
                        enablers=enablers,
                        payoffs=payoffs,
                        overlap=overlap,
                        draws=draws,
                    ),
                }
            pair_reports.append(
                {
                    "enabler": enabler["name"],
                    "payoff": payoff["name"],
                    "population": deck_size,
                    "enablers": enablers,
                    "payoffs": payoffs,
                    "overlap": overlap,
                    "formula": (
                        "1 - C(population - enablers, draws) / C(population, draws) "
                        "- C(population - payoffs, draws) / C(population, draws) "
                        "+ C(population - (enablers + payoffs - overlap), draws) / C(population, draws)"
                    ),
                    "by_turn": by_turn,
                    "assumptions": [
                        "Overlap is counted from exact shared printing IDs in the current main deck.",
                        "One additional card is seen per turn after the opening hand.",
                    ],
                }
            )
        return (
            {
                "categories": category_reports,
                "enabler_payoff": pair_reports,
                "plan_reliability": category_reports[0]["opening_hand"]["result"],
            },
            simulation,
            probability_values,
            limitations,
        )

    @staticmethod
    def _enabler_payoff_pairs(
        categories: list[dict[str, Any]],
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        enablers = [category for category in categories if category["kind"] == "enabler"]
        payoffs = [category for category in categories if category["kind"] == "payoff"]
        if enablers and payoffs:
            return [
                (enabler, payoff)
                for enabler in enablers
                for payoff in payoffs
                if enabler["name"] != payoff["name"]
            ]
        return [
            (categories[first], categories[second])
            for first in range(len(categories))
            for second in range(first + 1, len(categories))
        ]

    @staticmethod
    def _objective_vector(
        *,
        validation: dict[str, Any],
        analysis: dict[str, Any],
        plan_reliability: float | None,
    ) -> tuple[dict[str, float | None], dict[str, Any], list[str]]:
        limitations: list[str] = []
        objective_names = (
            "plan_reliability",
            "curve_quality",
            "interaction",
            "card_advantage",
            "resilience",
            "synergy",
            "matchup_fit",
        )
        if not validation["legal"]:
            limitations.extend(
                f"{objective} is unavailable because the revision does not satisfy hard constraints."
                for objective in objective_names
            )
            return (
                {
                    "legality": 0.0,
                    **{objective: None for objective in objective_names},
                },
                {
                    "availability": {
                        "hard_constraints_satisfied": False,
                        "reason": "DeckService validation did not produce a complete legal deck.",
                    }
                },
                limitations,
            )
        deck_size = analysis["deck_size"]
        role_breakdown = analysis["role_breakdown"]
        average_cost = analysis["average_cost"]
        format_name = analysis["format"]
        target_cost = 2.7 if format_name == TWIN_SUNS else 3.4

        if deck_size:
            def role_measure(*roles: str) -> float:
                return min(1.0, sum(role_breakdown.get(role, 0) for role in roles) / deck_size)

            interaction = role_measure("removal", "tempo")
            card_advantage = role_measure("card_advantage")
            resilience = role_measure("defense")
        else:
            interaction = None
            card_advantage = None
            resilience = None
            limitations.append(
                "Role-based objective measures are unavailable because the current main deck is empty."
            )
        if average_cost is None:
            curve_quality = None
            limitations.append("Curve quality is unavailable because resolved card costs are missing.")
        else:
            curve_quality = max(0.0, 1.0 - abs(float(average_cost) - target_cost) / target_cost)
        if plan_reliability is None:
            limitations.append(
                "plan_reliability is unavailable because it requires a supplied probability category."
            )

        matchup_scores = [
            score["score"]
            for score in analysis["matchup_scores"].values()
            if isinstance(score, dict) and isinstance(score.get("score"), (int, float))
        ]
        matchup_fit = sum(matchup_scores) / (100.0 * len(matchup_scores)) if matchup_scores else None
        if matchup_fit is None:
            limitations.append(
                "matchup_fit is unavailable because no supported target matchup score was produced."
            )

        vector: dict[str, float | None] = {
            "legality": 1.0 if validation["legal"] else 0.0,
            "plan_reliability": plan_reliability,
            "curve_quality": curve_quality,
            "interaction": interaction,
            "card_advantage": card_advantage,
            "resilience": resilience,
            "synergy": analysis["synergy_score"] / 100.0,
            "matchup_fit": matchup_fit,
        }
        return (
            vector,
            {
                "curve_quality": {
                    "average_cost": average_cost,
                    "target_average_cost": target_cost,
                    "formula": "max(0, 1 - abs(average_cost - target_average_cost) / target_average_cost)",
                },
                "role_measure": {
                    "formula": "min(1, detected_role_cards / resolved_main_deck_cards)",
                    "interaction_roles": ["removal", "tempo"],
                    "card_advantage_roles": ["card_advantage"],
                    "resilience_roles": ["defense"],
                },
                "matchup_fit": {
                    "formula": "mean(existing DeckService matchup scores) / 100",
                    "scores": analysis["matchup_scores"],
                },
            },
            limitations,
        )

    def _evaluate_candidate_swaps(
        self,
        *,
        session: BrewSession,
        revision: BrewRevision,
        horizons: list[int],
        mulligan_redraws: int,
        matchup_inputs: dict[str, Any],
        probability_categories: list[dict[str, Any]],
        candidate_swaps: list[dict[str, Any]] | None,
        collection_snapshot: CollectionSnapshot,
        base_objectives: dict[str, float | None],
        base_probability_values: dict[str, float | None],
        objective_directions: dict[str, Literal["min", "max"]] | None,
        unavailable_reason: str | None,
    ) -> list[dict[str, Any]]:
        if candidate_swaps is None:
            return []
        if not isinstance(candidate_swaps, list):
            raise ValueError("candidate_swaps must be a list of objects.")
        if unavailable_reason is not None:
            return [
                self._unavailable_candidate(
                    suggestion_id=raw_swap.get("suggestion_id", f"candidate-{index + 1}"),
                    raw_swap=raw_swap,
                    base_objectives=base_objectives,
                    base_probability_values=base_probability_values,
                    hard_constraints={"legal": None, "errors": [unavailable_reason]},
                    diagnostics=[unavailable_reason],
                )
                for index, raw_swap in enumerate(candidate_swaps)
            ]
        candidates: list[dict[str, Any]] = []
        for index, raw_swap in enumerate(candidate_swaps):
            if not isinstance(raw_swap, dict):
                raise ValueError("Each candidate swap must be an object.")
            suggestion_id = raw_swap.get("suggestion_id", f"candidate-{index + 1}")
            if not isinstance(suggestion_id, str) or not suggestion_id:
                raise ValueError("Each candidate swap needs a nonempty suggestion_id.")
            try:
                additions = self._resolve_decision_cards(raw_swap.get("adds", []))
                cuts = self._resolve_decision_cards(raw_swap.get("cuts", []))
                main_additions, sideboard_additions = _partition_decision_cards(additions)
                main_cuts, sideboard_cuts = _partition_decision_cards(cuts)
                candidate_revision = revision.model_copy(deep=True)
                candidate_revision.main_deck = self._apply_deck_changes(
                    candidate_revision.main_deck,
                    additions=main_additions,
                    cuts=main_cuts,
                )
                candidate_revision.sideboard = self._apply_deck_changes(
                    candidate_revision.sideboard,
                    additions=sideboard_additions,
                    cuts=sideboard_cuts,
                )
                self._validate_prospective_revision(
                    session,
                    candidate_revision,
                    collection_snapshot=collection_snapshot,
                )
                content, candidate_probability_values = self._evaluate_revision_content(
                    session=session,
                    revision=candidate_revision,
                    horizons=horizons,
                    mulligan_redraws=mulligan_redraws,
                    simulation_seed=1,
                    simulation_count=1,
                    matchup_inputs=matchup_inputs,
                    probability_categories=probability_categories,
                    include_goldfish=False,
                )
                if not content["hard_constraints"]["legal"]:
                    candidates.append(
                        self._unavailable_candidate(
                            suggestion_id=suggestion_id,
                            raw_swap=raw_swap,
                            base_objectives=base_objectives,
                            base_probability_values=base_probability_values,
                            hard_constraints=content["hard_constraints"],
                            diagnostics=[
                                *content["hard_constraints"]["errors"],
                                *content["limitations"],
                            ],
                        )
                    )
                    continue
                objectives = content["objective_vector"]
                candidates.append(
                    {
                        "suggestion_id": suggestion_id,
                        "accepted": False,
                        "adds": deepcopy(raw_swap.get("adds", [])),
                        "cuts": deepcopy(raw_swap.get("cuts", [])),
                        "objective_vector": objectives,
                        "objective_deltas": self._deltas(base_objectives, objectives),
                        "probability_deltas": self._deltas(
                            base_probability_values,
                            candidate_probability_values,
                        ),
                        "pareto_efficient": False,
                        "pareto_status": "unavailable",
                        "hard_constraints": content["hard_constraints"],
                        "diagnostics": [
                            *content["validation"]["errors"],
                            *content["limitations"],
                        ],
                    }
                )
            except BrewCollectionConflictError as exc:
                candidates.append(
                    self._unavailable_candidate(
                        suggestion_id=suggestion_id,
                        raw_swap=raw_swap,
                        base_objectives=base_objectives,
                        base_probability_values=base_probability_values,
                        hard_constraints={
                            "legal": False,
                            "errors": [str(exc)],
                            "collection_conflicts": exc.conflicts,
                        },
                        diagnostics=[str(exc)],
                    )
                )
            except (ValueError, TypeError, RuntimeError) as exc:
                candidates.append(
                    self._unavailable_candidate(
                        suggestion_id=suggestion_id,
                        raw_swap=raw_swap,
                        base_objectives=base_objectives,
                        base_probability_values=base_probability_values,
                        hard_constraints={"legal": False, "errors": [str(exc)]},
                        diagnostics=[str(exc)],
                    )
                )
        self._classify_candidate_pareto(
            candidates,
            base_objectives=base_objectives,
            objective_directions=objective_directions,
        )
        return candidates

    @staticmethod
    def _unavailable_candidate(
        *,
        suggestion_id: str,
        raw_swap: dict[str, Any],
        base_objectives: dict[str, float | None],
        base_probability_values: dict[str, float | None],
        hard_constraints: dict[str, Any],
        diagnostics: list[str],
    ) -> dict[str, Any]:
        return {
            "suggestion_id": suggestion_id,
            "accepted": False,
            "adds": deepcopy(raw_swap.get("adds", [])),
            "cuts": deepcopy(raw_swap.get("cuts", [])),
            "objective_vector": {key: None for key in base_objectives},
            "objective_deltas": {key: None for key in base_objectives},
            "probability_deltas": {key: None for key in base_probability_values},
            "pareto_status": "unavailable",
            "pareto_efficient": False,
            "hard_constraints": hard_constraints,
            "diagnostics": diagnostics,
        }

    @staticmethod
    def _deltas(
        baseline: dict[str, float | None],
        candidate: dict[str, float | None],
    ) -> dict[str, float | None]:
        return {
            key: (
                candidate.get(key) - baseline.get(key)
                if isinstance(candidate.get(key), (int, float))
                and not isinstance(candidate.get(key), bool)
                and isinstance(baseline.get(key), (int, float))
                and not isinstance(baseline.get(key), bool)
                else None
            )
            for key in baseline
        }

    @staticmethod
    def _classify_candidate_pareto(
        candidates: list[dict[str, Any]],
        *,
        base_objectives: dict[str, float | None],
        objective_directions: dict[str, Literal["min", "max"]] | None,
    ) -> None:
        if not candidates:
            return
        if objective_directions is not None and not isinstance(objective_directions, dict):
            raise ValueError("objective_directions must be an object.")
        requested_directions = objective_directions or {
            metric: "max" for metric in base_objectives
        }
        if any(direction not in {"min", "max"} for direction in requested_directions.values()):
            raise ValueError("objective_directions values must be min or max.")
        directions = {
            metric: direction
            for metric, direction in requested_directions.items()
            if metric in base_objectives
            and isinstance(base_objectives[metric], (int, float))
            and not isinstance(base_objectives[metric], bool)
        }
        comparable = [
            candidate
            for candidate in candidates
            if candidate["hard_constraints"]["legal"]
            and all(
                isinstance(candidate["objective_vector"].get(metric), (int, float))
                and not isinstance(candidate["objective_vector"].get(metric), bool)
                for metric in directions
            )
        ]
        unavailable = [candidate for candidate in candidates if candidate not in comparable]
        if not directions or not comparable:
            for candidate in candidates:
                candidate["pareto_status"] = "unavailable"
                candidate["pareto_efficient"] = False
                candidate["diagnostics"].append(
                    "Pareto classification is unavailable because the compared objective values are incomplete."
                )
            return
        for candidate in unavailable:
            candidate["pareto_status"] = "unavailable"
            candidate["pareto_efficient"] = False
            candidate["diagnostics"].append(
                "Pareto classification is unavailable because the candidate lacks comparable objectives."
            )
        alternatives = [
            {"id": "baseline", "objective_vector": base_objectives},
            *[
                {
                    "id": candidate["suggestion_id"],
                    "objective_vector": candidate["objective_vector"],
                }
                for candidate in comparable
            ],
        ]
        pareto = pareto_analysis(alternatives, directions=directions)
        statuses = {
            item["id"]: item
            for item in [*pareto["frontier"], *pareto["dominated"]]
        }
        for candidate in comparable:
            status = statuses[candidate["suggestion_id"]]
            candidate["pareto_efficient"] = status["pareto_efficient"]
            candidate["pareto_status"] = status["pareto_status"]
            if status.get("dominated_by"):
                candidate["diagnostics"].append(
                    f"Dominated by: {', '.join(str(item) for item in status['dominated_by'])}."
                )

    def _resolve_decision_cards(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not isinstance(entries, list):
            raise ValueError("Decision card entries must be a list.")
        resolved: list[dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("Each decision card entry must be an object.")
            card = self._resolve_exact_printing(entry)
            quantity = self._decision_quantity(entry)
            metadata = {
                key: deepcopy(value)
                for key, value in entry.items()
                if key
                not in {
                    "card",
                    "card_number",
                    "count",
                    "id",
                    "lookup_id",
                    "number",
                    "printing_id",
                    "quantity",
                    "set",
                    "set_code",
                }
            }
            resolved.append({**metadata, **card, "quantity": quantity})
        return resolved

    def _resolve_exact_printing(self, entry: dict[str, Any]) -> dict[str, Any]:
        printing_id = self._decision_printing_id(entry)
        set_code, card_number = printing_id.split("/", 1)
        if self.card_service.catalog.is_available():
            record = self.card_service.catalog.lookup(set_code, card_number)
            if record is None:
                raise BrewResolutionError(f"Could not resolve exact printing {printing_id}.")
            card = record.to_dict()
        else:
            card = self.card_service.lookup_card(set_code=set_code, card_number=card_number)
            if not isinstance(card, dict):
                raise BrewResolutionError(f"Could not resolve exact printing {printing_id}.")
            card = dict(card)
        resolved_id = str(card.get("lookup_id") or "")
        if resolved_id != printing_id:
            raise BrewResolutionError(
                f"Exact printing must use canonical SET/NNN text; {printing_id} resolves as {resolved_id}."
            )
        return card

    @staticmethod
    def _decision_printing_id(entry: dict[str, Any]) -> str:
        values = [
            entry.get("printing_id"),
            entry.get("lookup_id"),
            entry.get("id"),
            entry.get("card") if isinstance(entry.get("card"), str) else None,
        ]
        nested = entry.get("card")
        if isinstance(nested, dict):
            values.extend([nested.get("printing_id"), nested.get("lookup_id"), nested.get("id")])
        value = next((item for item in values if isinstance(item, str) and item.strip()), None)
        if value is None:
            set_code = entry.get("set_code") or entry.get("set")
            card_number = entry.get("card_number") or entry.get("number")
            if set_code is not None and card_number is not None:
                value = f"{set_code}/{card_number}"
        if not isinstance(value, str):
            raise BrewResolutionError("Each decision card requires an exact SET/NNN printing ID.")
        if value != value.strip():
            raise BrewResolutionError("Each decision card requires an exact SET/NNN printing ID.")
        parts = value.split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise BrewResolutionError("Each decision card requires an exact SET/NNN printing ID.")
        set_code, card_number = parts
        number_is_valid = (
            card_number[:-1].isdigit() if card_number[-1].isalpha() else card_number.isdigit()
        )
        if (
            not set_code[0].isalpha()
            or not set_code.isalnum()
            or len(set_code) < 2
            or len(set_code) > 8
            or not card_number[0].isdigit()
            or not number_is_valid
        ):
            raise BrewResolutionError("Each decision card requires an exact SET/NNN printing ID.")
        return f"{set_code}/{card_number}"

    @staticmethod
    def _decision_quantity(entry: dict[str, Any]) -> int:
        quantity = entry.get("quantity", entry.get("count", 1))
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 0:
            raise ValueError("Decision card quantities must be nonnegative integers.")
        return quantity

    @staticmethod
    def _require_text(value: object, label: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{label} must be a string.")
        return value

    @staticmethod
    def _require_dict_list(value: object, label: str) -> list[dict[str, Any]]:
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise ValueError(f"{label} must be a list of objects.")
        return value

    @staticmethod
    def _require_role_targets(value: object) -> dict[str, int]:
        if not isinstance(value, dict):
            raise ValueError("role_targets must be an object.")
        targets: dict[str, int] = {}
        for role, quantity in value.items():
            if not isinstance(role, str) or not role.strip():
                raise ValueError("role_targets must use nonempty string role names.")
            if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 0:
                raise ValueError("role_targets must use nonnegative integer quantities.")
            targets[role] = quantity
        return targets

    @staticmethod
    def _require_string_list(value: object, label: str) -> list[str]:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError(f"{label} must be a list of strings.")
        return list(value)

    @staticmethod
    def _validate_advisory_report(
        session: BrewSession,
        advisory_report_id: str | None,
        expected_revision: int,
        *,
        accept_stale_evidence: bool,
    ) -> None:
        if not isinstance(accept_stale_evidence, bool):
            raise ValueError("accept_stale_evidence must be a boolean.")
        if advisory_report_id is None:
            if accept_stale_evidence:
                raise ValueError(
                    "accept_stale_evidence requires a referenced advisory report from an older revision."
                )
            return
        if not isinstance(advisory_report_id, str) or not advisory_report_id:
            raise ValueError("advisory_report_id must be a nonempty string when provided.")
        report = next(
            (item for item in session.reports if item.report_id == advisory_report_id),
            None,
        )
        if report is None:
            raise ValueError(f"Unknown advisory report ID: {advisory_report_id}.")
        if report.revision == expected_revision:
            if accept_stale_evidence:
                raise ValueError(
                    "accept_stale_evidence is valid only for a referenced advisory report from an older revision."
                )
            return
        if not accept_stale_evidence:
            raise ValueError(
                f"Advisory report {advisory_report_id} is bound to revision {report.revision}, "
                f"not expected revision {expected_revision}; set accept_stale_evidence=true "
                "only to record an explicit stale-evidence acceptance."
            )

    @staticmethod
    def _is_substantive_change(
        *,
        parent: BrewRevision,
        revision: BrewRevision,
        additions: list[dict[str, Any]],
        cuts: list[dict[str, Any]],
        restore_revision: int | None,
    ) -> bool:
        return bool(
            additions
            or cuts
            or restore_revision is not None
            or revision.thesis != parent.thesis
            or revision.packages != parent.packages
            or revision.role_targets != parent.role_targets
            or revision.reservations != parent.reservations
            or revision.rejected_cards != parent.rejected_cards
        )

    def _apply_deck_changes(
        self,
        main_deck: list[dict[str, Any]],
        *,
        additions: list[dict[str, Any]],
        cuts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        deck: dict[Any, dict[str, Any]] = {}
        order: list[Any] = []
        for item in main_deck:
            if not isinstance(item, dict):
                raise ValueError("Stored main-deck entries must be objects.")
            quantity = self._decision_quantity(item)
            identity = canonical_key(item)
            if identity not in deck:
                deck[identity] = deepcopy(item)
                deck[identity]["quantity"] = quantity
                order.append(identity)
            else:
                deck[identity]["quantity"] += quantity

        for item in additions:
            identity = canonical_key(item)
            if identity not in deck:
                deck[identity] = deepcopy(item)
                order.append(identity)
            else:
                deck[identity]["quantity"] += item["quantity"]

        for item in cuts:
            identity = canonical_key(item)
            existing = deck.get(identity)
            if existing is None or existing["quantity"] < item["quantity"]:
                raise ValueError(
                    f"Cannot cut {item['quantity']} copy/copies of {item['display_name']}; the selected parent has fewer."
                )
            existing["quantity"] -= item["quantity"]

        return [deck[identity] for identity in order if deck[identity]["quantity"] > 0]

    def _validate_prospective_revision(
        self,
        session: BrewSession,
        revision: BrewRevision,
        *,
        collection_snapshot: CollectionSnapshot,
    ) -> None:
        all_entries = [*revision.main_deck, *revision.sideboard]
        sideboard_size = sum(self._decision_quantity(entry) for entry in revision.sideboard)
        if session.format_name == TWIN_SUNS and sideboard_size:
            raise ValueError("Twin Suns decks should not include a sideboard.")
        if session.format_name == PREMIER and sideboard_size > PREMIER_SIDEBOARD_MAX:
            raise ValueError(
                f"Premier sideboard max is {PREMIER_SIDEBOARD_MAX}; found {sideboard_size}."
            )
        quantities: dict[Any, int] = {}
        selected_printings: dict[Any, str] = {}
        for entry in all_entries:
            quantity = self._decision_quantity(entry)
            if not quantity:
                continue
            card_type = str(entry.get("card_type") or entry.get("Type") or "")
            if card_type not in {"Unit", "Event", "Upgrade"}:
                raise ValueError("Only Unit, Event, or Upgrade cards may enter a brew revision.")
            missing_aspects = sorted(
                set(entry.get("aspects") or entry.get("Aspects") or []) - set(session.legal_aspects)
            )
            if missing_aspects and not session.allow_off_aspect:
                raise ValueError(
                    f"Off-aspect card {entry.get('display_name') or entry.get('name')} requires "
                    f"{', '.join(missing_aspects)}."
                )
            identity = canonical_key(entry)
            quantities[identity] = quantities.get(identity, 0) + quantity
            selected_printings.setdefault(identity, str(entry.get("lookup_id") or entry.get("printing_id") or ""))

        for identity, quantity in quantities.items():
            card = next(entry for entry in all_entries if canonical_key(entry) == identity)
            format_limit = 1 if session.format_name == TWIN_SUNS else 3
            override = card_copy_override(card)
            effective_limit = (
                max(format_limit, override) if override is not None else format_limit
            )
            if quantity > effective_limit:
                raise ValueError(
                    f"Canonical copy limit is {effective_limit}; "
                    f"{identity.name} has {quantity} copies."
                )

        if session.only_owned:
            conflicts: list[dict[str, Any]] = []
            for identity, quantity in quantities.items():
                card = next(entry for entry in all_entries if canonical_key(entry) == identity)
                owned, _ = self._canonical_ownership(card, collection_snapshot)
                if quantity > owned:
                    conflicts.append(
                        {
                            "printing_id": selected_printings[identity],
                            "requested": quantity,
                            "owned": owned,
                        }
                    )
            if conflicts:
                raise BrewCollectionConflictError(conflicts)

    def _decision_error(
        self,
        exc: Exception,
        *,
        collection: dict[str, Any] | None,
        session: BrewSession | None,
        session_id: str | None,
    ) -> dict[str, Any]:
        result = self._error(
            exc,
            "Correct the explicit decision, revision, or collection state and retry.",
            session=session,
            session_id=session_id,
        )
        if collection is not None:
            result["collection"] = collection
        return result

    def _resolve_setup(
        self,
        *,
        format_name: str,
        leader_names: list[str],
        base_name: str,
        only_owned: bool,
        collection_snapshot: CollectionSnapshot,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        parsed = self.deck_service.parse_decklist(
            decklist={
                "leaders": leader_names,
                "bases": [base_name],
            },
            format_name=format_name,
        )
        self._require_unambiguous_entries(parsed.leaders, card_type="Leader", label="leader")
        self._require_unambiguous_entries(parsed.bases, card_type="Base", label="base")
        resolved = self.deck_service.resolve_deck(parsed)
        expected_leaders = PREMIER_LEADER_COUNT if format_name == PREMIER else TWIN_SUNS_LEADER_COUNT
        if sum(entry.quantity for entry in resolved.leaders) != expected_leaders:
            raise ValueError(f"{format_name.replace('_', ' ').title()} requires exactly {expected_leaders} leader(s).")
        if len(resolved.bases) != 1 or sum(entry.quantity for entry in resolved.bases) != 1:
            raise ValueError("A brew requires exactly one base.")
        if any((entry.card or {}).get("card_type") != "Leader" for entry in resolved.leaders):
            raise ValueError("Each selected leader must resolve to a Leader card.")
        if (resolved.bases[0].card or {}).get("card_type") != "Base":
            raise ValueError("The selected base must resolve to a Base card.")
        if format_name == TWIN_SUNS and len({canonical_key(entry.card or {}) for entry in resolved.leaders}) != 2:
            raise ValueError("Twin Suns requires two distinct canonical leaders.")
        if format_name == TWIN_SUNS and shared_alignment(resolved.leaders) is None:
            raise ValueError("Twin Suns leaders must share Heroism or Villainy.")

        leaders = [dict(entry.card or {}) for entry in resolved.leaders]
        base = dict(resolved.bases[0].card or {})
        if only_owned:
            leaders = [
                self._owned_setup_card(card, "leader", collection_snapshot)
                for card in leaders
            ]
            base = self._owned_setup_card(base, "base", collection_snapshot)
        return leaders, base

    def _require_unambiguous_entries(
        self,
        entries: list[Any],
        *,
        card_type: str,
        label: str,
    ) -> None:
        if not self.card_service.catalog.is_available():
            return
        for entry in entries:
            if entry.set_code and entry.card_number:
                exact = self.card_service.catalog.lookup(entry.set_code, entry.card_number)
                if exact is None:
                    raise BrewResolutionError(
                        f"Could not resolve exact {label} printing {entry.set_code}/{entry.card_number}."
                    )
                if exact.card_type != card_type:
                    raise BrewResolutionError(
                        f"Exact printing {exact.lookup_id} is a {exact.card_type}, not a {card_type}."
                    )
                continue

            candidates = self._name_candidates(entry.name, card_type)
            printing_candidates = {
                str(card["lookup_id"]): card
                for card in candidates
            }
            if len(printing_candidates) > 1:
                choices = sorted(
                    (
                        {"lookup_id": str(card["lookup_id"]), "display_name": str(card["display_name"])}
                        for card in printing_candidates.values()
                    ),
                    key=lambda card: (card["display_name"], card["lookup_id"]),
                )
                raise BrewResolutionError(
                    f"Ambiguous {label} '{entry.name}'. Use a full display name or SET/NNN.",
                    candidates=choices,
                )

    def _name_candidates(self, name: str, card_type: str) -> list[dict[str, Any]]:
        normalized = name.strip().casefold()
        cards = [
            card.to_dict()
            for card in self.card_service.catalog.all_cards()
            if card.card_type == card_type
        ]
        exact = [
            card
            for card in cards
            if normalized in {str(card["display_name"]).casefold(), str(card["name"]).casefold()}
        ]
        if exact:
            return exact
        prefix = [card for card in cards if str(card["display_name"]).casefold().startswith(normalized)]
        if prefix:
            return prefix
        return [card.to_dict() for card in self.card_service.catalog.search(name, filters={"type": card_type}, limit=100)]

    def _owned_setup_card(
        self,
        card: dict[str, Any],
        kind: str,
        collection_snapshot: CollectionSnapshot,
    ) -> dict[str, Any]:
        owned_printings = self._canonical_owned_printings(card, collection_snapshot)
        if not owned_printings:
            raise ValueError(f"The selected {kind} is not in the configured collection.")
        selected = owned_printings[0]
        return self._resolve_exact_printing(
            {"printing_id": f"{selected.set_code}/{selected.card_number.zfill(3)}"}
        )

    def _collection_snapshot(self) -> CollectionSnapshot:
        return self.collection_service.immutable_snapshot()

    def _collection_state(
        self,
        session: BrewSession,
        collection_snapshot: CollectionSnapshot,
    ) -> dict[str, Any]:
        if session.collection_path is None or session.collection_snapshot_hash is None:
            return {"tracked": False, "stale": False}
        if Path(session.collection_path) != collection_snapshot.storage_path:
            raise ValueError("Configured collection path does not match the session provenance path.")
        current_hash = collection_snapshot.sha256
        return {
            "tracked": True,
            "path": session.collection_path,
            "snapshot_hash": session.collection_snapshot_hash,
            "current_hash": current_hash,
            "stale": current_hash != session.collection_snapshot_hash,
        }

    def _candidate_context(
        self,
        *,
        session: BrewSession,
        intent: str,
        filters: dict[str, Any],
        cursor: str | None,
        limit: int,
        collection: dict[str, Any],
        collection_snapshot: CollectionSnapshot,
    ) -> dict[str, Any]:
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            raise ValueError("Context limit must be an integer from 1 to 100.")
        fingerprint = _query_fingerprint(session.session_id, intent, filters)
        offset = _decode_cursor(cursor, fingerprint) if cursor else 0
        candidates = self._catalog_candidates(session, filters, collection_snapshot)
        page = candidates[offset : offset + limit]
        next_offset = offset + len(page)
        return self._success(
            session,
            diagnostics=self._collection_diagnostics(collection),
            next_steps=["Record selected additions, cuts, reservations, or rejections explicitly."],
            cards=page,
            next_cursor=(
                _encode_cursor(next_offset, fingerprint) if next_offset < len(candidates) else None
            ),
            total_candidates=len(candidates),
            collection=collection,
        )

    def _catalog_candidates(
        self,
        session: BrewSession,
        filters: dict[str, Any],
        collection_snapshot: CollectionSnapshot,
    ) -> list[dict[str, Any]]:
        thesis = build_deck_thesis(
            session.theme,
            session.leader_cards,
            session.base_card,
            session.format_name,
            session.meta_context,
        )
        revision = session.revisions[session.current_revision]
        included = _included_quantities(revision)
        cards: list[dict[str, Any]] = []
        for record in self.card_service.catalog.all_cards():
            card = record.to_dict()
            ownership = self._ownership(card, collection_snapshot)
            if session.only_owned and not ownership["owned"]:
                continue
            roles = roles_for_card(card, thesis)
            package_tags = _package_tags(card, thesis.target_packages)
            inclusion = _inclusion(card, included)
            if not _matches_filters(
                card,
                filters,
                roles=list(roles.roles),
                package_tags=package_tags,
                ownership=ownership,
                inclusion=inclusion,
            ):
                continue
            cards.append(
                {
                    "printing_id": card["lookup_id"],
                    "card": card,
                    "ownership": ownership,
                    "inferred_roles": list(roles.roles),
                    "package_tags": package_tags,
                    "interactions": {
                        "provides": sorted(provides_set(card)),
                        "needs": sorted(needs_set(card)),
                    },
                    "inclusion": inclusion,
                    "_rank": _relevance_rank(card, session.theme),
                }
            )
        cards.sort(key=lambda item: (-item["_rank"], item["printing_id"]))
        for card in cards:
            card.pop("_rank")
        return cards

    def _ownership(
        self,
        card: dict[str, Any],
        collection_snapshot: CollectionSnapshot,
    ) -> dict[str, Any]:
        count, foil_count = self._canonical_ownership(card, collection_snapshot)
        return {
            "owned": count > 0,
            "count": count,
            "foil_count": foil_count,
        }

    def _canonical_owned_printings(
        self,
        card: dict[str, Any],
        collection_snapshot: CollectionSnapshot,
    ) -> list[Any]:
        target = canonical_key(card)
        matches = []
        for entry in collection_snapshot.entries:
            if entry.count <= 0:
                continue
            owned_card = self.card_service.catalog.lookup(entry.set_code, entry.card_number)
            if owned_card is None or canonical_key(owned_card.to_dict()) != target:
                continue
            matches.append(entry)
        return sorted(matches, key=lambda entry: (entry.set_code, entry.card_number))

    def _canonical_ownership(
        self,
        card: dict[str, Any],
        collection_snapshot: CollectionSnapshot,
    ) -> tuple[int, int]:
        printings = self._canonical_owned_printings(card, collection_snapshot)
        return (
            sum(entry.count for entry in printings),
            sum(entry.foil_count for entry in printings),
        )

    @staticmethod
    def _session_summary(session: BrewSession) -> dict[str, Any]:
        return {
            "session_id": session.session_id,
            "format_name": session.format_name,
            "stage": session.stage,
            "theme": session.theme,
            "leaders": session.leader_cards,
            "base": session.base_card,
            "legal_aspects": session.legal_aspects,
            "current_revision": session.current_revision,
            "only_owned": session.only_owned,
        }

    @staticmethod
    def _format_constraints(format_name: str) -> dict[str, Any]:
        if format_name == PREMIER:
            return {
                "leaders": PREMIER_LEADER_COUNT,
                "bases": 1,
                "main_deck_minimum": PREMIER_MAIN_DECK_MIN,
                "sideboard_maximum": PREMIER_SIDEBOARD_MAX,
                "default_copy_limit": 3,
            }
        return {
            "leaders": TWIN_SUNS_LEADER_COUNT,
            "bases": 1,
            "main_deck_exact": TWIN_SUNS_MAIN_DECK_MIN,
            "sideboard_maximum": 0,
            "default_copy_limit": 1,
            "leader_alignment": "shared Heroism or Villainy",
        }

    @staticmethod
    def _collection_diagnostics(collection: dict[str, Any]) -> list[dict[str, Any]]:
        if not collection.get("stale"):
            return []
        return [
            {
                "severity": "warning",
                "code": "collection_snapshot_stale",
                "message": "The configured collection differs from this session snapshot.",
            }
        ]

    @staticmethod
    def _success(
        brew_session: BrewSession,
        *,
        revision: int | None = None,
        diagnostics: list[dict[str, Any]] | None = None,
        next_steps: list[str] | None = None,
        **payload: Any,
    ) -> dict[str, Any]:
        return {
            "status": "ok",
            "session_id": brew_session.session_id,
            "revision": brew_session.current_revision if revision is None else revision,
            "stage": brew_session.stage,
            "diagnostics": list(diagnostics or []),
            "next_steps": list(next_steps or []),
            **payload,
        }

    @staticmethod
    def _error(
        exc: Exception,
        recovery_action: str,
        *,
        session: BrewSession | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        message = str(exc)
        result: dict[str, Any] = {
            "status": "fail",
            "session_id": session.session_id if session is not None else session_id,
            "revision": session.current_revision if session is not None else None,
            "stage": session.stage if session is not None else None,
            "diagnostics": [
                {
                    "severity": "error",
                    "code": exc.__class__.__name__,
                    "message": message,
                }
            ],
            "next_steps": [recovery_action],
            "error": {"message": message},
            "recovery_action": recovery_action,
        }
        if isinstance(exc, BrewResolutionError) and exc.candidates:
            result["error"]["candidates"] = exc.candidates
            result["recovery_action"] = "Use a full display name or exact SET/NNN from the listed candidates."
            result["next_steps"] = [result["recovery_action"]]
        return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _collection_hash(path: str | Path) -> str:
    return CollectionSnapshot.read(path).sha256


def _query_fingerprint(session_id: str, intent: str, filters: dict[str, Any]) -> str:
    payload = json.dumps(
        {"session_id": session_id, "intent": intent, "filters": filters},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _encode_cursor(offset: int, fingerprint: str) -> str:
    raw = json.dumps({"offset": offset, "fingerprint": fingerprint}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str, fingerprint: str) -> int:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode((cursor + padding).encode("ascii")))
        offset = payload["offset"]
        if payload["fingerprint"] != fingerprint or not isinstance(offset, int) or offset < 0:
            raise ValueError
        return offset
    except (KeyError, TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid or incompatible context cursor.") from exc


_CONTEXT_FILTER_KEYS = {
    "roles",
    "packages",
    "min_cost",
    "max_cost",
    "card_types",
    "aspects",
    "traits",
    "keywords",
    "text",
    "minimum_owned",
    "inclusion_state",
    "type",
    "aspect",
    "trait",
    "query",
}
_LIST_CONTEXT_FILTER_KEYS = {"roles", "packages", "card_types", "aspects", "traits", "keywords"}


def _normalize_context_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
    if filters is None:
        return {}
    if not isinstance(filters, dict):
        raise ValueError("Candidate filters must be an object.")
    unsupported = sorted(set(filters) - _CONTEXT_FILTER_KEYS)
    if unsupported:
        raise ValueError(f"Unsupported candidate filter: {unsupported[0]}")

    normalized: dict[str, Any] = {}
    for key in _LIST_CONTEXT_FILTER_KEYS:
        value = filters.get(key)
        if value is None:
            continue
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError(f"Candidate filter {key} must be a list of strings.")
        values = [item.strip() for item in value if item.strip()]
        if values:
            normalized[key] = values

    for key in ("min_cost", "max_cost", "minimum_owned"):
        value = filters.get(key)
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"Candidate filter {key} must be a nonnegative integer.")
        normalized[key] = value
    if (
        "min_cost" in normalized
        and "max_cost" in normalized
        and normalized["min_cost"] > normalized["max_cost"]
    ):
        raise ValueError("Candidate filter min_cost cannot exceed max_cost.")

    for key in ("text", "type", "aspect", "trait", "query"):
        value = filters.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"Candidate filter {key} must be a string.")
        value = value.strip()
        if value:
            normalized[key] = value

    inclusion_state = filters.get("inclusion_state")
    if inclusion_state is not None:
        if inclusion_state not in {"included", "excluded", "any"}:
            raise ValueError("Candidate filter inclusion_state must be included, excluded, or any.")
        if inclusion_state != "any":
            normalized["inclusion_state"] = inclusion_state
    return normalized


def _matches_filters(
    card: dict[str, Any],
    filters: dict[str, Any],
    *,
    roles: list[str],
    package_tags: list[str],
    ownership: dict[str, Any],
    inclusion: dict[str, Any],
) -> bool:
    def normalized_values(values: list[str]) -> set[str]:
        return {value.casefold() for value in values}

    card_type = str(card.get("card_type", "")).casefold()
    aspects = normalized_values([str(item) for item in card.get("aspects", [])])
    traits = normalized_values([str(item) for item in card.get("traits", [])])
    keywords = normalized_values([str(item) for item in card.get("keywords", [])])
    role_values = normalized_values(roles)
    package_values = normalized_values(package_tags)
    if "type" in filters and card_type != filters["type"].casefold():
        return False
    if "aspect" in filters and filters["aspect"].casefold() not in aspects:
        return False
    if "trait" in filters and filters["trait"].casefold() not in traits:
        return False
    if "query" in filters and filters["query"].casefold() not in json.dumps(card, sort_keys=True).casefold():
        return False
    if "card_types" in filters and card_type not in normalized_values(filters["card_types"]):
        return False
    if "aspects" in filters and not normalized_values(filters["aspects"]).issubset(aspects):
        return False
    if "traits" in filters and not normalized_values(filters["traits"]).issubset(traits):
        return False
    if "keywords" in filters and not normalized_values(filters["keywords"]).issubset(keywords):
        return False
    if "roles" in filters and not normalized_values(filters["roles"]).issubset(role_values):
        return False
    if "packages" in filters and not normalized_values(filters["packages"]).issubset(package_values):
        return False
    if "text" in filters and filters["text"].casefold() not in json.dumps(card, sort_keys=True).casefold():
        return False
    cost = parse_int(card.get("cost"))
    if "min_cost" in filters and (cost is None or cost < filters["min_cost"]):
        return False
    if "max_cost" in filters and (cost is None or cost > filters["max_cost"]):
        return False
    if "minimum_owned" in filters and ownership["count"] < filters["minimum_owned"]:
        return False
    if "inclusion_state" in filters:
        is_included = inclusion["state"] == "included"
        if filters["inclusion_state"] == "included" and not is_included:
            return False
        if filters["inclusion_state"] == "excluded" and is_included:
            return False
    return True


def _partition_decision_cards(
    entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    main_deck: list[dict[str, Any]] = []
    sideboard: list[dict[str, Any]] = []
    for entry in entries:
        zone = entry.get("zone", "main_deck")
        if zone == "main_deck":
            main_deck.append(entry)
        elif zone == "sideboard":
            sideboard.append(entry)
        else:
            raise ValueError("Decision card zone must be main_deck or sideboard.")
    return main_deck, sideboard


def _included_quantities(revision: BrewRevision) -> dict[str, int]:
    quantities: dict[str, int] = {}
    for item in [*revision.main_deck, *revision.sideboard]:
        printing_id = str(item.get("lookup_id") or item.get("printing_id") or "")
        if printing_id:
            quantities[printing_id] = quantities.get(printing_id, 0) + int(item.get("quantity", 1))
    return quantities


def _inclusion(card: dict[str, Any], included: dict[str, int]) -> dict[str, Any]:
    quantity = included.get(str(card["lookup_id"]), 0)
    return {"state": "included" if quantity else "not_in_revision", "quantity": quantity}


def _package_tags(card: dict[str, Any], target_packages: tuple[str, ...]) -> list[str]:
    text = " ".join(
        [
            str(card.get("front_text") or ""),
            str(card.get("back_text") or ""),
            " ".join(str(item) for item in card.get("traits", [])),
        ]
    ).lower()
    tags: set[str] = set()
    if "when played" in text or "return a friendly" in text or "return a unit" in text:
        tags.add("replay_engine")
    for package in target_packages:
        if package == "force_engine" and ("force" in text or "jedi" in text):
            tags.add(package)
        elif package == "token_swarm" and "token" in text:
            tags.add(package)
        elif package == "discard_engine" and "discard" in text:
            tags.add(package)
        elif package == "exhaust_engine" and ("exhaust" in text or "ready" in text):
            tags.add(package)
    return sorted(tags)


def _relevance_rank(card: dict[str, Any], theme: str) -> int:
    terms = [term for term in theme.lower().split() if len(term) > 2]
    haystack = json.dumps(card, sort_keys=True).lower()
    return sum(term in haystack for term in terms)
