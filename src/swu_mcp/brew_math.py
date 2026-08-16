"""Pure probability, simulation, and Pareto helpers for brew evaluation."""

from __future__ import annotations

import math
import random
from statistics import NormalDist
from typing import Any, Literal


def _require_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _validate_population(population: int, successes: int, draws: int) -> None:
    _require_int("population", population)
    _require_int("successes", successes)
    _require_int("draws", draws)
    if population < 1:
        raise ValueError("population must be at least 1")
    if not 0 <= successes <= population:
        raise ValueError("successes must be between 0 and population")
    if not 0 <= draws <= population:
        raise ValueError("draws must be between 0 and population")


def _no_success_probability(population: int, successes: int, draws: int) -> float:
    remaining = population - successes
    denominator = math.comb(population, draws)
    if draws > remaining:
        return 0.0
    return math.comb(remaining, draws) / denominator


def hypergeometric_pmf(
    population: int, successes: int, draws: int, hits: int
) -> float:
    """Return the exact finite-population probability of exactly ``hits``."""

    _validate_population(population, successes, draws)
    _require_int("hits", hits)
    minimum_hits = max(0, draws - (population - successes))
    maximum_hits = min(draws, successes)
    if hits < minimum_hits or hits > maximum_hits:
        return 0.0
    return (
        math.comb(successes, hits)
        * math.comb(population - successes, draws - hits)
        / math.comb(population, draws)
    )


def probability_at_least_one(population: int, successes: int, draws: int) -> float:
    """Return the exact probability that a sample contains one success."""

    _validate_population(population, successes, draws)
    return 1.0 - _no_success_probability(population, successes, draws)


def probability_enabler_and_payoff(
    population: int,
    enablers: int,
    payoffs: int,
    overlap: int,
    draws: int,
) -> float:
    """Return the exact probability of drawing both categories."""

    _validate_population(population, 0, draws)
    _require_int("enablers", enablers)
    _require_int("payoffs", payoffs)
    _require_int("overlap", overlap)
    if not 0 <= enablers <= population:
        raise ValueError("enablers must be between 0 and population")
    if not 0 <= payoffs <= population:
        raise ValueError("payoffs must be between 0 and population")
    if not 0 <= overlap <= min(enablers, payoffs):
        raise ValueError("overlap must be between 0 and the category counts")
    union = enablers + payoffs - overlap
    if union > population:
        raise ValueError("enablers and payoffs union must not exceed population")

    return (
        1.0
        - _no_success_probability(population, enablers, draws)
        - _no_success_probability(population, payoffs, draws)
        + _no_success_probability(population, union, draws)
    )


def mulligan_adjusted(success_probability: float, redraws: int = 1) -> float:
    """Apply the independent full-redraw approximation to a success probability.

    The approximation treats each redraw as a fresh full sample. The actual game
    keeps selected cards and redraws only the remainder, so this is advisory.
    """

    if isinstance(success_probability, bool) or not isinstance(
        success_probability, (int, float)
    ):
        raise ValueError("success_probability must be a finite number between 0 and 1")
    if not math.isfinite(success_probability) or not 0 <= success_probability <= 1:
        raise ValueError("success_probability must be a finite number between 0 and 1")
    _require_int("redraws", redraws)
    if redraws < 0:
        raise ValueError("redraws must be non-negative")
    return 1.0 - (1.0 - success_probability) ** (redraws + 1)


def wilson_interval(
    successes: int, trials: int, confidence: float = 0.95
) -> tuple[float, float]:
    """Return a Wilson score interval for a binomial proportion."""

    _require_int("successes", successes)
    _require_int("trials", trials)
    if trials < 1:
        raise ValueError("trials must be at least 1")
    if not 0 <= successes <= trials:
        raise ValueError("successes must be between 0 and trials")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("confidence must be between 0 and 1")
    if not math.isfinite(confidence) or not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")

    z = NormalDist().inv_cdf(1.0 - (1.0 - confidence) / 2.0)
    proportion = successes / trials
    z_squared = z * z
    denominator = 1.0 + z_squared / trials
    center = (proportion + z_squared / (2.0 * trials)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1.0 - proportion) / trials
            + z_squared / (4.0 * trials * trials)
        )
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def _objective_vector(alternative: dict[str, Any]) -> dict[str, Any]:
    for key in ("objective_vector", "metrics"):
        value = alternative.get(key)
        if isinstance(value, dict):
            return value
    return alternative


def _alternative_identifier(alternative: dict[str, Any], index: int) -> Any:
    return alternative.get("id", alternative.get("name", index))


def _dominates(
    left: dict[str, Any],
    right: dict[str, Any],
    directions: dict[str, Literal["min", "max"]],
) -> bool:
    left_vector = _objective_vector(left)
    right_vector = _objective_vector(right)
    no_worse = True
    strictly_better = False
    for metric, direction in directions.items():
        left_value = left_vector[metric]
        right_value = right_vector[metric]
        if direction == "min":
            if left_value > right_value:
                no_worse = False
            elif left_value < right_value:
                strictly_better = True
        else:
            if left_value < right_value:
                no_worse = False
            elif left_value > right_value:
                strictly_better = True
    return no_worse and strictly_better


def pareto_analysis(
    alternatives: list[dict[str, Any]],
    directions: dict[str, Literal["min", "max"]],
) -> dict[str, list[dict[str, Any]]]:
    """Classify alternatives while retaining ties on the Pareto frontier."""

    if not isinstance(alternatives, list):
        raise ValueError("alternatives must be a list")
    if not isinstance(directions, dict) or not directions:
        raise ValueError("directions must be a non-empty dictionary")
    if any(direction not in {"min", "max"} for direction in directions.values()):
        raise ValueError("directions values must be 'min' or 'max'")

    for alternative in alternatives:
        if not isinstance(alternative, dict):
            raise ValueError("each alternative must be a dictionary")
        vector = _objective_vector(alternative)
        for metric in directions:
            if metric not in vector:
                raise ValueError(f"alternative is missing objective metric: {metric}")
            value = vector[metric]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"objective metric must be numeric: {metric}")
            if not math.isfinite(value):
                raise ValueError(f"objective metric must be finite: {metric}")

    frontier: list[dict[str, Any]] = []
    dominated: list[dict[str, Any]] = []
    for index, alternative in enumerate(alternatives):
        dominated_by = [
            _alternative_identifier(other, other_index)
            for other_index, other in enumerate(alternatives)
            if other_index != index and _dominates(other, alternative, directions)
        ]
        result = dict(alternative)
        if dominated_by:
            result["pareto_status"] = "dominated"
            result["pareto_efficient"] = False
            result["dominated_by"] = dominated_by
            dominated.append(result)
        else:
            result["pareto_status"] = "frontier"
            result["pareto_efficient"] = True
            frontier.append(result)
    return {"frontier": frontier, "dominated": dominated}


def seeded_draw_simulation(
    deck_size: int,
    category_counts: dict[str, int],
    hand_size: int,
    draws_by_turn: dict[int, int],
    trials: int,
    seed: int,
) -> dict[str, Any]:
    """Simulate cumulative cards seen by turn using a local seeded generator.

    Values in ``draws_by_turn`` are the number of cards drawn after the opening
    hand by each requested turn. Each result reports trials containing at least
    one card from a category and the corresponding hit rate.
    """

    _require_int("deck_size", deck_size)
    _require_int("hand_size", hand_size)
    _require_int("trials", trials)
    _require_int("seed", seed)
    if deck_size < 1:
        raise ValueError("deck_size must be at least 1")
    if not 0 <= hand_size <= deck_size:
        raise ValueError("hand_size must be between 0 and deck_size")
    if trials < 1:
        raise ValueError("trials must be at least 1")
    if not isinstance(category_counts, dict):
        raise ValueError("category_counts must be a dictionary")
    for category, count in category_counts.items():
        if not isinstance(category, str) or not category:
            raise ValueError("category names must be non-empty strings")
        _require_int(f"category count for {category}", count)
        if count < 0:
            raise ValueError(f"category count for {category} must be non-negative")
    if sum(category_counts.values()) > deck_size:
        raise ValueError("category counts must not exceed deck_size")
    if not isinstance(draws_by_turn, dict):
        raise ValueError("draws_by_turn must be a dictionary")
    for turn, draws in draws_by_turn.items():
        _require_int("turn", turn)
        _require_int(f"draws for turn {turn}", draws)
        if turn < 1:
            raise ValueError("turns must be at least 1")
        if draws < 0:
            raise ValueError("draws by turn must be non-negative")
        if hand_size + draws > deck_size:
            raise ValueError("hand size plus draws must not exceed deck_size")

    categories = [
        category
        for category in sorted(category_counts)
        for _ in range(category_counts[category])
    ]
    categories.extend(["other"] * (deck_size - len(categories)))
    rng = random.Random(seed)
    turn_results: dict[str, dict[str, dict[str, float | int]]] = {}
    for turn, draws in sorted(draws_by_turn.items()):
        hit_counts = {category: 0 for category in sorted(category_counts)}
        cards_seen = hand_size + draws
        for _ in range(trials):
            sample = rng.sample(categories, cards_seen)
            for category in hit_counts:
                if category in sample:
                    hit_counts[category] += 1
        turn_results[str(turn)] = {
            category: {
                "hits": hits,
                "probability": hits / trials,
            }
            for category, hits in hit_counts.items()
        }

    return {
        "deck_size": deck_size,
        "category_counts": {category: category_counts[category] for category in sorted(category_counts)},
        "hand_size": hand_size,
        "draws_by_turn": {str(turn): draws for turn, draws in sorted(draws_by_turn.items())},
        "trials": trials,
        "seed": seed,
        "results": turn_results,
    }
