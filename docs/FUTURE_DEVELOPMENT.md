# Future Development

Notes on known gaps in the deck-brewing pipeline. Each is a meta-level
extension beyond the existing combo-package framework — same problem
shape (encode a heuristic the brewer currently misses) but a different
implementation than `combo_packages.py`.

## 1. Trait clustering

**Problem.** Two decks can each have "30 on-aspect units" but one is
all REBEL and the other is a scattered mix of REBEL/REPUBLIC/IMPERIAL/
FRINGE. The first executes a tribal strategy; the second is a vanilla
on-aspect pile. The current brewer scores them identically.

**Why the existing tools miss it.** Combo packages tag cards by
*mechanic* (force_engine, exhaust_engine, etc.). Trait concentration is
a *statistical* property of the deck as a whole — no single card
encodes it. The interaction term in `deck_service.generate_deck` does
read shared traits but caps at one pair per candidate, which doesn't
capture cumulative tribal density.

**Suggested implementation.**
- Compute per-deck trait Herfindahl index (sum of squared trait
  fractions). Decks that concentrate in one trait score higher.
- Bonus during scoring: `+ K × max_trait_fraction²`, capped.
- Bonus tribally relevant *payoff* cards more when their trait matches
  the deck's dominant trait. The current `interaction_glossary` already
  has trait-payoff signals; weight them by deck-wide trait density.
- Add a `swu_collection_tribal_density` MCP tool that returns the
  user's strongest tribes (REBEL, JEDI, BOUNTY HUNTER, MANDALORIAN,
  TROOPER, CAPITAL SHIP) ranked by enabler/payoff balance, similar to
  the existing combo profile.

**Files involved.**
- `src/swu_mcp/deck_service.py` — `generate_deck`, `interaction_term`,
  `analyze_deck`
- New helper module possibly: `src/swu_mcp/trait_clustering.py`

## 2. Aspect-pair archetype recognition

**Problem.** Some leader pairs have established competitive identities
documented in articles (Bossk + Boba SOR = bounty hunter aggro;
Anakin + Padmé = unit-flood control; Yoda + Rey w/ Command base =
Force engine). The brewer treats every legal pair as a blank slate
and reverse-engineers the archetype from card density. Where a pair
has a *named* archetype with a known good shell, the brewer should at
minimum recognize it and seed the deck pool toward known cards.

**Why the existing tools miss it.** No archetype lookup exists. The
`combo_packages` framework is purely textual; archetypes are
human-defined consensus.

**Suggested implementation.**
- Add `src/swu_mcp/archetypes.py` with a hand-curated list of
  `KnownArchetype` entries: leader IDs, base, archetype name,
  signature card list (5–10 named cards), short description, source
  citation.
- During `rank_leader_pairs`, if a candidate pair matches a known
  archetype, attach the archetype name + signature card check to the
  result entry. Bonus +5–10 if the brewed deck includes ≥3 of the
  signature cards (validates the brewer found the right shell).
- Source archetypes from: SWU-DB hot decks, Garbage Rollers tier
  lists, Deploy Your Leader articles, sw-unlimited-db Twin Suns
  rankings. Refresh quarterly.
- Optional: a `swu_known_archetypes` MCP tool that lists supported
  archetypes for browsing.

**Files involved.**
- New `src/swu_mcp/archetypes.py`
- `src/swu_mcp/deck_service.py` — `rank_leader_pairs` adds the lookup
- `src/swu_mcp/server.py` — exposes the new tool

## 3. Power-level normalization across sets

**Problem.** Card power creeps over time. A 3-cost 3/3 from set 1
(SOR) is statistically weaker than a 3-cost 3/4 with a keyword from
set 4 (LOF). The current `power_score` function in `deck_service.py`
treats them the same. The brewer happily fills slots with vanilla
older commons when newer commons would be strictly better picks at
the same cost.

**Why the existing tools miss it.** `power_score` is a closed-form
heuristic (stat efficiency × 3 + per-keyword bonus + rarity bump). It
doesn't index against per-set baselines. Calibration was done once
against 10 Premier decks (per the docstring) and never refreshed.

**Suggested implementation.**
- Compute per-set power baselines: for each (cost, type, set), median
  power_score. Store as data sidecar (`data/set_power_baselines.json`).
- Adjust `power_score` to return a relative score: `raw_score /
  median_for_set_at_cost`. Cards above their cohort's median get a
  boost; cards below get a slight penalty.
- Alternatively, add a simple "set recency" multiplier — newer sets
  get a small bonus reflecting design-creep. Less precise but easier
  to maintain.
- Calibration script: `scripts/recalibrate_power_baselines.py` that
  pulls all printed cards via the SWU-DB API and recomputes baselines.
  Run on each new set release.

**Files involved.**
- `src/swu_mcp/deck_service.py` — `power_score`
- New `data/set_power_baselines.json`
- New `scripts/recalibrate_power_baselines.py`

## Priority

If picking one to ship first:
1. **Trait clustering** is the highest-impact and lowest-risk addition
   — the user's data already shows tribal pools (110 VEHICLE, 63 FORCE,
   53 FIGHTER) that the brewer doesn't reward concentrating into.
2. **Power normalization** is medium impact, medium effort. Mostly a
   one-time calibration job.
3. **Archetype recognition** is highest effort (curation + maintenance)
   and most fragile to meta shifts. Save for after the brewer is more
   mature.
