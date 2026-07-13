from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .deck_evaluator import evaluate_deck_cards
from .deck_thesis import DeckThesis


@dataclass(frozen=True)
class SwapRecord:
    removed: str
    added: str
    reason: str
    score_delta: float


@dataclass(frozen=True)
class OptimizationResult:
    cards: tuple[dict[str, Any], ...]
    initial_score: float
    final_score: float
    swaps: tuple[SwapRecord, ...]


def _name(card: dict[str, Any]) -> str:
    return str(card.get("display_name") or card.get("Name") or "")


def optimize_card_list(
    cards: list[dict[str, Any]],
    role_pools: dict[str, list[dict[str, Any]]],
    thesis: DeckThesis,
    *,
    max_iterations: int = 20,
) -> OptimizationResult:
    current = list(cards)
    initial = evaluate_deck_cards(current, thesis)
    current_score = initial.total_score
    swaps: list[SwapRecord] = []
    candidates = [card for pool in role_pools.values() for card in pool]

    for _ in range(max_iterations):
        best_swap: tuple[float, int, dict[str, Any]] | None = None
        current_names = {_name(card) for card in current}
        for candidate in candidates:
            if _name(candidate) in current_names:
                continue
            for idx, existing in enumerate(current):
                trial = current[:idx] + [candidate] + current[idx + 1 :]
                trial_score = evaluate_deck_cards(trial, thesis).total_score
                delta = trial_score - current_score
                if delta > 0 and (best_swap is None or delta > best_swap[0]):
                    best_swap = (delta, idx, candidate)
        if best_swap is None:
            break
        delta, idx, candidate = best_swap
        removed = current[idx]
        current[idx] = candidate
        current_score += delta
        swaps.append(
            SwapRecord(
                removed=_name(removed),
                added=_name(candidate),
                reason="Improved evaluator score.",
                score_delta=round(delta, 2),
            )
        )

    return OptimizationResult(
        cards=tuple(current),
        initial_score=initial.total_score,
        final_score=round(current_score, 2),
        swaps=tuple(swaps),
    )
