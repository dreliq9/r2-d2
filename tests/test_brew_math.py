import json
import math

import pytest

from swu_mcp.brew_math import (
    hypergeometric_pmf,
    mulligan_adjusted,
    pareto_analysis,
    probability_at_least_one,
    probability_enabler_and_payoff,
    seeded_draw_simulation,
    wilson_interval,
)


def test_probability_at_least_one_matches_closed_form():
    actual = probability_at_least_one(population=50, successes=3, draws=6)
    expected = 1 - math.comb(47, 6) / math.comb(50, 6)
    assert actual == pytest.approx(expected, abs=1e-12)


def test_probability_at_least_one_has_exact_boundaries():
    assert probability_at_least_one(population=50, successes=0, draws=6) == 0.0
    assert probability_at_least_one(population=50, successes=50, draws=6) == 1.0
    assert probability_at_least_one(population=50, successes=3, draws=0) == 0.0


def test_enabler_and_payoff_uses_inclusion_exclusion():
    actual = probability_enabler_and_payoff(
        population=50, enablers=6, payoffs=8, overlap=2, draws=9
    )
    expected = 1 - math.comb(44, 9) / math.comb(50, 9) \
        - math.comb(42, 9) / math.comb(50, 9) \
        + math.comb(38, 9) / math.comb(50, 9)
    assert actual == pytest.approx(expected, abs=1e-12)


def test_hypergeometric_pmf_handles_zero_impossible_and_ordinary_hits():
    assert hypergeometric_pmf(50, 3, 6, 0) == pytest.approx(
        math.comb(47, 6) / math.comb(50, 6), abs=1e-12
    )
    assert hypergeometric_pmf(50, 3, 6, 4) == 0.0
    assert hypergeometric_pmf(10, 4, 3, 2) == pytest.approx(
        math.comb(4, 2) * math.comb(6, 1) / math.comb(10, 3), abs=1e-12
    )


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ((0, 0, 0), "population must be at least 1"),
        ((10, 11, 2), "successes must be between 0 and population"),
        ((10, 4, 11), "draws must be between 0 and population"),
    ],
)
def test_hypergeometric_inputs_are_validated(args, message):
    with pytest.raises(ValueError, match=message):
        probability_at_least_one(*args)


def test_mulligan_adjusted_uses_independent_full_redraw_approximation():
    assert mulligan_adjusted(0.25) == pytest.approx(1 - 0.75**2)
    assert mulligan_adjusted(0.25, redraws=2) == pytest.approx(1 - 0.75**3)
    assert mulligan_adjusted(0.0) == 0.0
    assert mulligan_adjusted(1.0) == 1.0


@pytest.mark.parametrize(
    ("successes", "trials", "expected"),
    [
        (0, 100, (0.0, 0.03699349820698565)),
        (50, 100, (0.4038315303659957, 0.5961684696340044)),
        (100, 100, (0.9630065017930143, 1.0)),
    ],
)
def test_wilson_interval_at_zero_midpoint_and_full_success(
    successes, trials, expected
):
    assert wilson_interval(successes, trials) == pytest.approx(expected, abs=1e-12)


def test_seeded_draw_simulation_is_byte_for_byte_reproducible():
    inputs = dict(
        deck_size=50,
        category_counts={"enabler": 6, "payoff": 8},
        hand_size=6,
        draws_by_turn={1: 1, 2: 1, 3: 1},
        trials=200,
        seed=17,
    )
    first = seeded_draw_simulation(**inputs)
    second = seeded_draw_simulation(**inputs)
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second, sort_keys=True, separators=(",", ":")
    )
    assert first["seed"] == 17
    assert first["trials"] == 200


def test_pareto_analysis_respects_min_max_and_labels_dominated_alternatives():
    alternatives = [
        {"id": "balanced", "objective_vector": {"cost": 2, "reliability": 0.8}},
        {"id": "cheap", "objective_vector": {"cost": 1, "reliability": 0.7}},
        {"id": "reliable", "objective_vector": {"cost": 3, "reliability": 0.9}},
        {"id": "dominated", "objective_vector": {"cost": 3, "reliability": 0.7}},
    ]

    result = pareto_analysis(
        alternatives, directions={"cost": "min", "reliability": "max"}
    )

    assert [item["id"] for item in result["frontier"]] == [
        "balanced",
        "cheap",
        "reliable",
    ]
    assert result["dominated"][0]["id"] == "dominated"
    assert result["dominated"][0]["pareto_status"] == "dominated"
    assert result["dominated"][0]["pareto_efficient"] is False


def test_pareto_analysis_keeps_tied_vectors_visible():
    alternatives = [
        {"id": "first", "metrics": {"risk": 1, "value": 5}},
        {"id": "tie", "metrics": {"risk": 1, "value": 5}},
        {"id": "worse", "metrics": {"risk": 2, "value": 4}},
    ]

    result = pareto_analysis(alternatives, directions={"risk": "min", "value": "max"})

    assert [item["id"] for item in result["frontier"]] == ["first", "tie"]
    assert result["frontier"][0]["pareto_status"] == "frontier"
    assert result["frontier"][1]["pareto_efficient"] is True
