# SWU-MCP

`SWU-MCP` is a FastMCP-powered Star Wars Unlimited `stdio` server with three major capability areas:

- `swu_search_cards`
- `swu_lookup_card`
- `swu_random_card`
- `swu_get_image`
- `swu_upload_deck`
- `swu_draw_card`
- `swu_view_hand`
- `swu_view_board`
- `swu_mulligan`
- `swu_sideboard`
- `swu_resource_phase`
- `swu_play_card`
- `swu_move_card`
- `swu_set_card_state`
- `swu_defeat_card`
- `swu_validate_deck`
- `swu_analyze_deck`
- `swu_suggest_cards`
- `swu_generate_deck`
- `swu_export_deck`
- `swu_start_game`
- `swu_get_game_state`
- `swu_get_legal_actions`
- `swu_take_game_action`
- `swu_take_ai_turn`

The MCP transport is `stdio`. Card data comes from the live [swu-db API](https://www.swu-db.com/api) first and can fall back to a local catalog JSON file when the network is unavailable.

## Quick Start

```bash
uv sync
uv run python scripts/start_stdio.py
```

## Claude Desktop Config

```json
{
  "mcpServers": {
    "swu-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "/Users/adamsteen/Desktop/SWU-MCP codename Hyperspeed",
        "run",
        "python",
        "scripts/start_stdio.py"
      ]
    }
  }
}
```

## Optional Offline Catalog

Build a local catalog snapshot for API fallback:

```bash
uv run python scripts/build_catalog.py
```

Then point the server at it:

```bash
export SWU_MCP_CARD_CATALOG_PATH=/Users/adamsteen/Desktop/SWU-MCP\ codename\ Hyperspeed/data/catalog/cards.json
uv run python scripts/start_stdio.py
```

## Environment Variables

- `SWU_MCP_API_BASE_URL` defaults to `https://api.swu-db.com`
- `SWU_MCP_CARD_CATALOG_PATH` points to a local JSON fallback file
- `SWU_MCP_CACHE_DIR` defaults to `.swu-mcp-cache`
- `SWU_MCP_DEFAULT_LIMIT` defaults to `10`

## Notes

- Search filters compile into the native SWU DB syntax, so natural text and advanced filter clauses can be mixed.
- Random card selection uses the search endpoint and samples locally from the result set.
- The server auto-builds a local card catalog under `data/catalog/cards.json` if `swu-db` search gets flaky, which makes deck uploads and brewing far more reliable than a pure live-API wrapper.
- Deck sessions now track hand, library, discard, resources, ground arena, space arena, leader deployment, base state, ready/exhausted flags, and simple counters like damage, experience, and shields.
- `swu_analyze_deck`, `swu_suggest_cards`, and `swu_generate_deck` accept `target_matchups` and `meta_context` so you can tune for specific environments instead of generic ladder play.
- The game engine now supports two-player setup, legal-action generation, resource turns, unit/event play, leader deployment, combat, base damage, a stack/priority loop, and a basic AI pilot loop.
- `swu_take_game_action` now accepts `resolve_effect` and `pass_priority`, and stack-bearing turns expose targetable options plus priority passes through `swu_get_legal_actions`.
- The current stack engine handles common card text patterns such as direct damage to units or bases, drawing cards, shields, experience, exhausting units, readying the source or attached unit, upgrade attachment, and `Restore` healing on attack.
- Attachable upgrades now track their host, carry simple static buffs like `+X/+Y`, can grant key keywords such as `Sentinel`, and are discarded automatically when the attached card leaves play.
- `Ambush`, `Sentinel`, `Saboteur`, `Overwhelm`, shields, experience, leader defeat/revert, and basic `When Played` / `On Attack` text patterns are supported in the current simulator.
- Attack triggers now pause for stack interaction before combat damage is assigned, so Claude can choose targets, pass priority, and then continue into combat instead of skipping that window.
- Current gameplay is still a pragmatic rules engine, not a full comprehensive-rules simulator yet. It is strongest for iterative playtesting and AI sparring, and weaker around complex upgrade conditions, nested optional triggers, temporary end-of-phase buffs/debuffs, and deep edge-case timing.
- Premier validation currently checks `1` leader, `1` base, `50+` main-deck cards, `10` card sideboard max, `3` copy max, and off-aspect penalty reporting.
- Twin Suns validation uses the current post-March 14, 2025 baseline in this implementation: `2` leaders sharing Heroism or Villainy, `1` base, `80+` singleton main deck, and no sideboard.

## Example Prompts

- "Upload this Luke ECL list, draw an opening hand, play my 2-drop to ground, and mark it exhausted."
- "Analyze this deck into aggro and control with `target_matchups` of `['aggro', 'control']`."
- "Suggest four swaps for space-heavy metas with `meta_context` pressure of `{'space': 0.6, 'aggro': 0.4}`."
- "Generate a budget Heroism Rebel deck tuned for aggro and space matchups."
- "Start a game with my deck against a generated villainy aggro deck, then show my legal actions."
- "Take my action to play Alliance Dispatcher, then let Claude take its turn."
- "Play Open Fire targeting their Battlefield Marine, pass priority, and let Claude respond on the stack."
- "Attach Protector to my Battlefield Marine, then show whether Claude can still attack my base."
