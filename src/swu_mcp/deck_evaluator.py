from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .card_roles import roles_for_card
from .deck_thesis import DeckThesis


@dataclass(frozen=True)
class CardDiagnostic:
    card_name: str
    roles: tuple[str, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvaluationWarning:
    code: str
    message: str


@dataclass(frozen=True)
class DeckEvaluation:
    total_score: float
    axis_scores: dict[str, float]
    metrics: dict[str, float]
    card_diagnostics: tuple[CardDiagnostic, ...] = ()
    warnings: tuple[EvaluationWarning, ...] = ()


def _pct(actual: int, target: int) -> float:
    if target <= 0:
        return 100.0
    return max(0.0, min(100.0, (actual / target) * 100.0))


def evaluate_deck_cards(cards: list[dict[str, Any]], thesis: DeckThesis) -> DeckEvaluation:
    role_counts = {role: 0 for role in thesis.role_targets}
    diagnostics: list[CardDiagnostic] = []
    for card in cards:
        profile = roles_for_card(card, thesis)
        for role in profile.roles:
            role_counts[role] = role_counts.get(role, 0) + 1
        diagnostics.append(
            CardDiagnostic(
                card_name=str(card.get("display_name") or card.get("Name") or ""),
                roles=profile.roles,
            )
        )

    role_scores = [
        _pct(role_counts.get(role, 0), target.minimum)
        for role, target in thesis.role_targets.items()
        if target.minimum > 0 and role_counts.get(role, 0) > 0
    ]
    role_coverage = sum(role_scores) / len(role_scores) if role_scores else 100.0

    upgrade_count = sum(1 for card in cards if str(card.get("card_type") or card.get("Type")) == "Upgrade")
    carrier_count = role_counts.get("upgrade_carrier", 0)
    carrier_ratio = carrier_count / max(upgrade_count, 1)
    upgrade_carrier_risk = 100.0 if upgrade_count <= 4 else max(0.0, min(100.0, carrier_ratio * 100.0))

    warnings: list[EvaluationWarning] = []
    if upgrade_carrier_risk < 70:
        warnings.append(
            EvaluationWarning(
                code="upgrade_carrier_risk",
                message=f"{upgrade_count} upgrades but only {carrier_count} upgrade carriers.",
            )
        )

    axis_scores = {
        "role_coverage": round(role_coverage, 2),
        "upgrade_carrier_risk": round(upgrade_carrier_risk, 2),
    }
    total_score = round((axis_scores["role_coverage"] * 0.7) + (axis_scores["upgrade_carrier_risk"] * 0.3), 2)
    return DeckEvaluation(
        total_score=total_score,
        axis_scores=axis_scores,
        metrics={
            "upgrade_count": float(upgrade_count),
            "upgrade_carrier_count": float(carrier_count),
        },
        card_diagnostics=tuple(diagnostics),
        warnings=tuple(warnings),
    )
