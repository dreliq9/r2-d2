# Human-Grade Deckbuilder Generator Design

## Goal

Upgrade the current first-pass Star Wars Unlimited deck generator into a deckbuilding system that can match or exceed a strong human builder for collection-aware Premier and Twin Suns brewing.

The system should do more than pick high-scoring cards. It should form a deck thesis, reserve role slots, build multiple candidate lists, test them, cut weak cards, explain why cards earn their slots, and use known archetypes and benchmark lists where available.

## Current Problems

The current generator has useful pieces, but they are not organized into a human-like deckbuilding loop.

- Card identity and ownership are printing-oriented. A requested owned card can resolve to an unowned variant and then disappear from the deck or leader set.
- Twin Suns leader requests can silently produce an illegal one-leader deck when a requested leader fails resolution.
- Candidate collection is a global top-N pool. Strong but low-token cards can be excluded before scoring.
- The builder is greedy and single-pass. It never revisits cards after the deck context changes.
- Synergy and interaction scores reward generic density. Common packages such as Vehicle/Pilot can look better than the intended leader plan.
- The simulator exists, but generator output is not tested through goldfish or matchup gauntlets.
- Known decklists, competitive research, and hand-authored archetype knowledge exist in the repo but are not first-class brewer inputs.
- Exhaustive leader-pair ranking fully brews every pair, making interactive exploration too slow.

## Non-Goals

- Do not attempt a complete SWU rules engine before improving deckbuilding quality.
- Do not require live network access for normal generation.
- Do not replace deterministic card reasoning with opaque model-only output.
- Do not make every archetype depend on curated data; unknown decks still need a good heuristic path.

## Target Workflow

The optimized generator should follow this flow:

1. Resolve requested leaders, base, collection, format, and theme into canonical card identities.
2. Build a structured deck thesis from leaders, theme, format, and meta context.
3. Produce role-specific candidate pools from owned cards or the full catalog.
4. Generate several initial legal lists from those role pools.
5. Evaluate each list on multiple axes.
6. Run local swap optimization to improve weak axes.
7. Optionally run goldfish or AI gauntlet simulations.
8. Return the best deck plus an explanation of the plan, key cards, weak cards, and next testing recommendations.

## Architecture

### 1. Canonical Card Identity

Add a canonical identity layer that separates card identity from printing identity.

Canonical identity should be based on normalized name, subtitle, type, and a stable key. Owned printings should map to the same canonical card. Generation should choose an owned printing after deciding that the canonical card belongs in the deck.

Required behavior:

- Requested leaders must resolve to canonical leaders.
- If `only_owned=True`, requested leaders and base must resolve to owned canonical cards or fail loudly.
- Twin Suns generation must never return a one-leader deck.
- Main-deck ownership checks should count all owned printings of the same canonical card.
- Validation should report both canonical identity and chosen printing when useful.

### 2. Deck Thesis

Introduce a `DeckThesis` model. It converts the user prompt and leaders into structured constraints and preferences.

Fields:

- `format_name`
- `leaders`
- `base`
- `legal_aspects`
- `target_packages`
- `role_targets`
- `type_targets`
- `curve_targets`
- `arena_targets`
- `must_include`
- `avoid_packages`
- `signature_cards`
- `matchup_priorities`
- `notes`

Examples:

- Kylo Ren plus Admiral Trench should produce an upgrade/discard thesis with upgrade density, discard outlets, recursion payoffs, cheap carriers, defensive early plays, and enough removal to survive until Kylo deploys.
- A Vehicle/Pilot theme should intentionally activate Pilot/Vehicle, reserve vehicle and pilot slots, and avoid treating generic upgrades as vehicle payoffs unless they actually attach to or reward vehicles.
- A known Cad Bane/Jabba shell should prioritize Underworld and Bounty Hunter density, cheap units, ping synergy, and bounty payoffs.

### 3. Role-Aware Candidate Pools

Replace the single global candidate pool with role-specific pools.

Core roles:

- early_unit
- midgame_unit
- finisher
- removal
- tempo
- card_advantage
- engine_enabler
- engine_payoff
- upgrade
- upgrade_carrier
- resource_ramp
- defensive_stabilizer
- matchup_tech

Each candidate should carry:

- canonical identity
- chosen printing
- roles
- package tags
- role score
- power score
- ownership count
- explanation snippets

The builder should fill role targets first, then use flexible slots for high-value cards.

### 4. Multi-Axis Evaluator

Add a deck evaluator that returns a structured `DeckEvaluation`.

Axes:

- legality and ownership
- curve health
- role coverage
- engine assembly
- payoff/enabler balance
- card type balance
- arena balance
- removal and interaction density
- draw/filter density
- dead-card risk
- upgrade carrier risk
- off-aspect burden
- archetype fit
- matchup fit
- opening-hand quality
- simulation performance when available

The evaluator should return raw metrics, normalized scores, and card-level warnings.

Important card-level questions:

- What role does this card fill?
- Is that role already oversupplied?
- Does the card depend on missing support?
- Is it dead without a specific board state?
- Is it merely a generic stat card when the deck needs engine density?
- Is there a better owned card for the same role?

### 5. Iterative Swap Optimizer

Add an optimizer that improves a generated deck through local search.

Inputs:

- initial deck candidates
- candidate pool by role
- evaluator
- max iterations
- optional locked cards
- optional excluded cards

Process:

1. Evaluate current deck.
2. Identify weak axes and weak cards.
3. Generate candidate swaps.
4. Re-evaluate each swap.
5. Keep swaps that improve total score without violating hard constraints.
6. Stop after convergence or iteration limit.

The optimizer should produce a change log:

- card removed
- card added
- reason
- score delta
- affected roles

### 6. Simulation Feedback

Use the existing game simulator as a feedback layer, not as the sole truth.

Simulation modes:

- goldfish: opening quality, resource curve, engine assembly, dead-card rate.
- gauntlet: run against generated or benchmark archetypes.
- focused line test: test specific plans such as "Kylo deploy with at least two upgrades in discard."

Simulation metrics:

- win rate
- average base damage dealt/taken
- turn of first meaningful board
- turn of engine online
- cards stranded in hand
- resource misses
- removal pressure
- leader deployment success

Simulator limitations must be surfaced in reports. A result should say when the rules engine cannot fully model a relevant mechanic.

### 7. Archetype And Meta Layer

Add an archetype registry with curated records.

`KnownArchetype` fields:

- archetype id
- format
- leaders
- preferred bases
- name
- description
- signature cards
- role targets
- package targets
- avoid patterns
- benchmark decklists
- source notes
- last reviewed date

Uses:

- Seed deck thesis for known leader pairs.
- Score archetype fit.
- Explain why a generated deck deviates from known shells.
- Provide benchmark opponents for gauntlets.

Competitive research files and hand-authored decklists should become fixtures. The generator does not need to copy them, but it should reproduce expected shape when asked for the same archetype.

### 8. Leader-Pair Ranking Performance

Change leader-pair ranking from full exhaustive brewing to two stages.

Stage 1: fast shortlist.

- score leader text
- score owned collection support
- score archetype match
- score aspect coverage
- score package loop potential
- score base availability

Stage 2: full generation.

- only brew top candidates
- optionally include full optimized decklists
- cache card tags and interaction sets

This should keep interactive ranking responsive while preserving quality for finalists.

## MCP Surface

Add or evolve tools:

- `swu_generate_optimized_deck`: thesis, generation, evaluation, swap optimization, optional simulation.
- `swu_explain_deck_slots`: card-by-card role and keep/cut reasoning.
- `swu_evaluate_deck`: structured evaluator without generation.
- `swu_optimize_deck`: improve an uploaded deck through swaps.
- `swu_run_deck_gauntlet`: simulate a deck against benchmark opponents.
- `swu_known_archetypes`: list known archetype records and supported shells.

Existing tools should remain stable. `swu_generate_deck` can keep returning a fast first-pass brew and point users to `swu_generate_optimized_deck` for higher-quality output.

## Testing Strategy

Unit tests:

- canonical identity maps owned variants correctly.
- requested leaders fail loudly when unresolved or unowned.
- Twin Suns generation never emits illegal one-leader decks.
- thesis parsing creates expected role targets for known leaders.
- candidate role tagging handles false positives such as `non-Vehicle`.
- evaluator flags dead upgrades with too few carriers.
- optimizer accepts beneficial swaps and rejects illegal swaps.

Golden tests:

- Kylo/Trench produces a discard-upgrade shell with meaningful upgrade density.
- Qui-Gon/Avar produces a Force/replay shell when both leaders are owned.
- Cad Bane/Jabba produces Underworld/Bounty Hunter density.
- Luke/Ackbar produces Vehicle/Pilot density only when that is the intended thesis.

Benchmark tests:

- known competitive decklists pass evaluator expectations for their archetypes.
- generated archetype decks match expected shape within tolerance.
- leader-pair ranking completes within a fixed time budget.

Simulation tests:

- goldfish reports opening and engine metrics.
- gauntlet runs are deterministic with a seed.
- simulator limitations are included when mechanics are approximated.

## Phased Implementation

### Phase 1: Hardening

- canonical identity model
- owned canonical lookup
- fail-fast leader/base resolution
- generation legality guardrails
- rank-pair timeout/performance instrumentation

### Phase 2: Thesis And Roles

- `DeckThesis`
- role target derivation
- role-aware candidate tagging
- role-aware initial builder

### Phase 3: Evaluator

- `DeckEvaluation`
- card-level diagnostics
- dead-card and support-risk checks
- structured report output

### Phase 4: Optimizer

- local swap loop
- locked/excluded cards
- swap explanation log
- improved `suggest_cards` integration

### Phase 5: Simulation Feedback

- goldfish metrics
- focused line tests
- gauntlet runner
- seeded deterministic reports

### Phase 6: Archetypes And Benchmarks

- `KnownArchetype` registry
- curated initial archetypes
- benchmark deck fixtures
- archetype-fit scoring

### Phase 7: MCP Polish

- new optimized generation tools
- structured output schemas
- concise user-facing explanations
- docs and examples

## Success Criteria

- Requested owned leaders resolve correctly across printings.
- Illegal generated decks are treated as errors, not successful outputs.
- Generated decks explain each card's role.
- Optimized decks improve over first-pass decks on evaluator score.
- Kylo/Trench, Qui-Gon/Avar, Cad Bane/Jabba, and Vehicle/Pilot benchmark scenarios produce recognizably correct shells.
- Leader-pair ranking returns useful top candidates within an interactive time budget.
- Simulation-backed reports identify real deck weaknesses such as dead upgrades, missing carriers, low removal, or curve stalls.

## Open Implementation Choices

- Whether archetype records live as Python data, JSON, or Markdown plus parsed front matter.
- Exact scoring weights for evaluator axes.
- How many generated candidates and swap iterations are the default for interactive use.
- Which benchmark archetypes should ship first.

These choices should be resolved in the implementation plan, not during this design approval step.
