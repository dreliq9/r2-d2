# R2-D2

A Star Wars Unlimited MCP server built with [FastMCP](https://github.com/jlowin/fastmcp). Search cards, build decks, validate formats, analyze the meta, and simulate two-player games — all through Claude Code, Claude Desktop, or any MCP-compatible client.

Card data comes from the live [SWU DB API](https://www.swu-db.com/api) first and automatically falls back to the bundled local catalog when the API is unavailable.

## Capabilities

### Card Database
| Tool | What it does |
|------|-------------|
| `swu_search_cards` | Natural text search with **typed** structured filters (aspect/type/arena/rarity/set as enums; cost/power/hp as `{op, value}` comparators). Returns a typed `SearchResult`. |
| `swu_lookup_card` | Exact lookup by name or set/number. Returns a typed `CardDetail`. |
| `swu_random_card` | Random card from a filtered pool. Returns a typed `CardSummary`. |
| `swu_get_image` | Front or back art URL for any card. |

#### Typed search filters (v0.3.0)

`swu_search_cards`, `swu_lookup_card`, and `swu_random_card` now return Pydantic models instead of opaque dicts. FastMCP serializes them as both `content` (human-readable text) and `structuredContent` (typed JSON) — agents can read `.cards[0].cost` directly without parsing string keys.

Filters are typed too. Aspect/type/arena/rarity/set are `Literal[...]` enums, so the agent sees the valid options in the tool schema and typos like `aspect="Cunninng"` are rejected before the API call. Numeric stats use a structured `{op, value}` instead of magic strings:

```python
swu_search_cards(
    query="Vader",
    filters={"aspect": "Villainy", "type": "Leader",
             "cost": {"op": ">=", "value": 5}},
)
```

Deck and game tools still return `dict` — that refactor is staged for a follow-up.

### Deck Building
| Tool | What it does |
|------|-------------|
| `swu_upload_deck` | Parse a decklist into a stateful session |
| `swu_validate_deck` | Check legality for Premier or Twin Suns (leaders, base, copy limits, aspect penalties) |
| `swu_analyze_deck` | Resource curve, aspect breakdown, synergy score, role analysis |
| `swu_suggest_cards` | Targeted card suggestions for a stated goal or matchup |
| `swu_generate_deck` | First-pass brew from a theme, leaders, and format |
| `swu_export_deck` | Export a session to a shareable decklist |

### Game Simulation
| Tool | What it does |
|------|-------------|
| `swu_start_game` | Two-player setup with deck loading |
| `swu_get_game_state` | Current board state, hand, resources, damage |
| `swu_get_legal_actions` | Available actions with targeting options |
| `swu_take_game_action` | Execute an action (play, attack, pass, etc.) |
| `swu_take_ai_turn` | Let the AI pilot take a full turn |
| `swu_draw_card` / `swu_view_hand` / `swu_view_board` | Card management |
| `swu_play_card` / `swu_move_card` / `swu_defeat_card` / `swu_set_card_state` | Direct board manipulation |
| `swu_mulligan` / `swu_resource_phase` / `swu_sideboard` | Phase management |

## Quick Start

```bash
uv sync
uv run python scripts/start_stdio.py
```

## Claude Code / Claude Desktop Config

Add to `~/.mcp.json`:

```json
{
  "mcpServers": {
    "r2-d2": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/r2-d2",
        "run",
        "python",
        "scripts/start_stdio.py"
      ]
    }
  }
}
```

## Offline Catalog

A bundled card catalog (`data/catalog/cards.json`) is auto-discovered at startup. The server uses it as a fallback whenever the live API is unavailable — no configuration needed.

To rebuild the catalog from the latest API data:

```bash
uv run python scripts/build_catalog.py
```

## Environment Variables

All optional — sensible defaults are built in.

| Variable | Default | Purpose |
|----------|---------|---------|
| `SWU_MCP_API_BASE_URL` | `https://api.swu-db.com` | Live card data API |
| `SWU_MCP_CARD_CATALOG_PATH` | Auto-discovered from `data/catalog/` | Local JSON fallback |
| `SWU_MCP_CACHE_DIR` | `.swu-mcp-cache` | Per-card response cache |
| `SWU_MCP_DEFAULT_LIMIT` | `10` | Default search result limit |

## Format Support

**Premier** — 1 leader, 1 base, 50+ main deck (3x copy limit), 10-card sideboard, off-aspect penalty reporting.

**Twin Suns** — 2 leaders sharing Heroism or Villainy, 1 base, 80+ singleton main deck, no sideboard.

## Game Engine

The simulator supports two-player games with:
- Resource turns, unit/event play, leader deployment, combat, base damage
- Stack/priority loop with targeting and responses
- Ambush, Sentinel, Saboteur, Overwhelm, Shielded, Restore, Raid, Hidden
- When Played / On Attack / When Defeated trigger patterns
- Upgrade attachment with static buffs and keyword grants
- Basic AI pilot for sparring

This is a pragmatic rules engine for playtesting and AI sparring, not a comprehensive rules simulator. Edge cases around complex upgrade conditions, nested optional triggers, and deep timing interactions are not fully covered.

## Example Prompts

- "Search for all Cunning leaders from Legends of the Force"
- "Generate a Twin Suns deck with Cad Bane and Jabba the Hutt"
- "Upload this decklist, analyze it, and suggest swaps for an aggro-heavy meta"
- "Start a game with my Qui-Gon deck against a generated Villainy aggro deck"
- "Take my action to play Boba Fett, then let the AI respond"

## License

[MIT](LICENSE)
