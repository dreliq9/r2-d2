# Qui-Gon Jinn + Avar Kriss — Twin Suns (When-Played / Force value)

**Format**: Twin Suns (80-card, 1x each)
**Alignment**: Heroism
**Aspects**: Command · Cunning · Heroism · Vigilance (strictly on-aspect — no Villainy/Aggression)
**Source**: r2-d2 collection-aware brew (`only_owned`), post-engine-upgrade
**Date**: 2026-06-08 (rebrew — folds in newly-purchased engine pieces; supersedes the 2026-06-01 build, archived as `quigon-avar-kriss-twin-suns.BACKUP-20260601.md`)
**Companion**: `~/Desktop/SWU-QuiGon-Avar-acquisition-tierlist.md` (upgrade path / pickups)

## Engine state at this build

- **Aspect-legality gate** (`582f59d`) — hard on-aspect filter; 0 off-aspect cards, 0 resource burden
- **Replay-loop modeling** (`f363e9c`) — `effect:replay` interaction token: bounce/recast enablers ↔ When-Played payoffs now score as a loop
- **Replay-quality grade** (`fffe81a`) — free recast > open bounce > capped bounce > discard recur (`REPLAY_QUALITY_W = 2.0`)
- **`replay_enabler` fix** (`7505fa2`) — catches qualified friendly bounce, excludes enemy bounce
- Base = Nightsister Lair (Force-token engine); cache anchored to project root

## Leaders & Base

- 1x **Qui-Gon Jinn - Student of the Living Force** [LOF/016] — Cunning/Heroism · Special
- 1x **Avar Kriss - Marshal of Starlight** [LOF/007] — Command/Heroism · Rare
- 1x **Nightsister Lair - Dathomir** [LOF/020] — Vigilance · Common, 28 HP, Force engine

## Profile

- 62 Units / 14 Events / 4 Upgrades
- Average cost: **2.99** (was 3.42)
- Curve: 1×0 · 11×1 · 22×2 · 17×3 · 17×4 · 8×5 · 3×6 · 1×7+
- Aspect split: Heroism 38 · Cunning 35 · Command 28 · Vigilance 17
- Roles: board 62 · tempo 32 · defense 24 · removal 20 · cardadv 13
- Top traits: VEHICLE 29 · REBEL 18 · FIGHTER 15 · PILOT 14 · FORCE 11 · REPUBLIC 10 · FRINGE 10 · JEDI 8
- Top keywords: Piloting 13 · Restore 8 · Sentinel 7 · Ambush 5 · Shielded 5 · Hidden 3
- Synergy score (legacy heuristic): 92
- **Interaction density**: 360.1 avg/card · 4.39 per-pair (was 175.4 / 2.14)
- Validation: **legal** — 2 leaders · 1 base · 80 main · 0 off-aspect burden

## Main Deck (80)

### Units (62)
1x Academy Graduate [JTL/058] — Vigilance · Common x
1x Admiral Ackbar - Brilliant Strategist [SOR/097] — Command/Heroism · Rare x
1x Admiral Yularen - Fleet Coordinator [JTL/047] — Vigilance/Heroism · Rare x
1x Alliance Dispatcher [SOR/093] — Command/Heroism · Common x
1x Anakin Skywalker - I'll Try Spinning [JTL/197] — Cunning/Heroism · Uncommon x
1x Astromech Pilot [JTL/057] — Vigilance · Uncommon x
1x Blade Squadron B-Wing [JTL/199] — Cunning/Heroism · Common x
1x Blue Leader - Scarif Air Support [JTL/096] — Command/Heroism ·  Uncommon x
1x BoShek - Charismatic Smuggler [JTL/215] — Cunning · Uncommon x
1x Bright Hope - The Last Transport [SOR/099] — Command/Heroism · Uncommon x
1x Cantina Bouncer [SOR/202] — Cunning · Uncommon x
1x Cargo Juggernaut [SOR/068] — Vigilance · Common x
1x Cloaked StarViper [JTL/067] — Vigilance · Common x
1x Clone Pilot [JTL/108] — Command · Common x
1x Cobb Vanth - The Marshal [SHD/115] — Command · Rare x
1x Dagger Squadron Pilot [JTL/196] — Cunning/Heroism · Common x
1x Death Space Skirmisher [JTL/217] — Cunning · Common x
1x Dilapidated Ski Speeder [JTL/248] — Heroism · Common
1x Dooku - It is Too Late [LOF/211] — Cunning · Uncommon x
1x Dornean Gunship [JTL/116] — Command · Uncommon x
1x Echo - Restored [SHD/099] — Command/Heroism · Uncommon x
1x Echo Base Engineer [JTL/044] — Vigilance/Heroism · Common x
1x Geonosis Patrol Fighter [TWI/215] — Cunning · Common x
1x Hera Syndulla - We've Lost Enough [JTL/045] — Vigilance/Heroism · Uncommon x
1x Independent Smuggler [JTL/211] — Cunning · Common x
1x Itinerant Warrior [LOF/048] — Vigilance/Heroism · Common
1x J-Type Nubian Starship [LOF/194] — Cunning/Heroism · Common x
1x Jarek Yeager - Coordinating With The Resistance [JTL/109] — Command · Uncommon x
1x Kanan Jarrus - Spectre One [LAW/089] — Cunning/Vigilance/Heroism · Uncommon x
1x Kimoglia Heavy Fighter [JTL/222] — Cunning · Common x
1x Leia Organa - Pilots, To Your Stations [JTL/097] — Command/Heroism · Uncommon x
1x Luke Skywalker - You Still With Me? [JTL/592] — Command/Heroism · Rare x
1x Milodon Rider [LAW/240] — Cunning · Common x
1x Oppo Rancisis - Ancient Councilor [LOF/105] — Command · Legendary x
1x Paige Tico - Dropping the Hammer [JTL/046] — Vigilance/Heroism · Uncommon x
1x Paladin Training Corvette [LOF/099] — Command/Heroism · Common x
1x Pelta Supply Frigate [TWI/095] — Command/Heroism · Common x
1x Phantom - Spectre Shuttle [LAW/144] — Command/Heroism · Rare x
1x Pirated Starfighter [SOR/209] — Cunning · Uncommon x
1x Poe Dameron - One Hell of a a Pilot [JTL/100] — Command/Heroism · Uncommon x
1x Point Rain Reclaimer [LOF/092] — Command/Heroism · Common x
1x Qui-Gon Jinn - Influencing Chance [LAW/237] — Cunning · Rare
1x Qui-Gon Jinn's Aethersprite - Guided by the Force [LOF/197] — Cunning/Heroism · Special x
1x R2-D2 - Full of Solutions [TWI/193] — Cunning/Heroism · Uncommon x
1x Razor Crest - Ride For Hire [JTL/223] — Cunning · Uncommon x
1x Red Leader - Form Up [JTL/101] — Command/Heroism · Uncommon x
1x Red Squadron X-Wing [JTL/051] — Vigilance/Heroism · Common x
1x Refugee of The Path [LOF/242] — Heroism · Common x
1x Resistance Blue Squadron [JTL/102] — Command/Heroism · Common x
1x Rio Durant - Beckett's Right Hands [LAW/093] — Cunning/Vigilance · Rare x
1x Rogue Squadron Skirmisher [SOR/101] — Command/Heroism · Uncommon x
1x Sabine's Masterpiece - Crazy Colorful [JTL/250] — Heroism · Rare x
1x Sidon Ithano - The Crimson Corsair [JTL/213] — Cunning · Rare x
1x Skyway Cloud Car [JTL/220] — Cunning · Common x
1x Stinger Mantis - Where Are We Going? [LOF/198] — Cunning/Heroism · Uncommon x
1x Subjugating Starfighter [TWI/112] — Command · Common x
1x Trace Martez - Trusting Sister [JTL/066] — Vigilance · Uncommon x
1x Trade Federation Shuttle [TWI/060] — Vigilance · Common x
1x Tranquility - Inspiring Flagship [TWI/246] — Heroism · Rare x
1x U-Wing Lander [JTL/070] — Vigilance · Uncommon x
1x Vanguard Ace [SOR/191] — Cunning/Heroism · Uncommon x
1x Youngling Padawan [LOF/193] — Cunning/Heroism · Common x

### Events (14)
1x A Precarious Predicament [LOF/222] — Cunning · Uncommon x
1x Direct Hit [JTL/078] — Vigilance · Common x
1x Directed by the Force [LOF/123] — Command · Uncommon x
1x Electromagnetic Pulse [JTL/230] — Cunning · Common x
1x Focus Fire [JTL/129] — Command · Common x
1x Prepare for Takeoff [JTL/128] — Command · Common x
1x Punch It [JTL/231] — Cunning · Common x
1x Sneak Attack [SOR/219] — Cunning · Rare x
1x Sweep the Area [JTL/233] — Cunning · Uncommonx
1x The Burden of Masters [LOF/125] — Command · Rare x
1x The Will of the Force [LOF/227] — Cunning · Common x
1x Three Lessons [LOF/225] — Cunning · Uncommon x
1x Its Worse

### Upgrades (4)
1x Ascension Cable [LOF/215] — Cunning · Common x
1x Heirloom Lightsaber [LOF/053] — Vigilance/Heroism · Common x
1x Pillio Star Compass [LOF/122] — Command · Uncommon x
1x Qui-Gon Jinn's Lightsaber [LOF/201] — Cunning/Heroism · Special x

## Rebrew changelog (2026-06-08)

Re-ran the collection-aware brewer against the current collection. 33 cards swapped in/out. The bounce/replay package the old build couldn't field (it wasn't owned yet) is now in: **Rio Durant – Beckett's Right Hands**, **Qui-Gon Jinn – Influencing Chance**, **Cantina Bouncer**, **Pirated Starfighter**, **Bright Hope**, plus the Spectre When-Played sub-package (**Kanan Jarrus – Spectre One**, **Phantom – Spectre Shuttle**, **Echo – Restored**) and **Milodon Rider** / **Geonosis Patrol Fighter**. Net effect: avg cost 3.42 → 2.99, interaction density 175 → 360.

**Added (33)**

*Units (28)*
- + Admiral Ackbar - Brilliant Strategist [SOR/097] — Command/Heroism · Rare
- + Alliance Dispatcher [SOR/093] — Command/Heroism · Common
- + Anakin Skywalker - I'll Try Spinning [JTL/197] — Cunning/Heroism · Uncommon
- + Bright Hope - The Last Transport [SOR/099] — Command/Heroism · Uncommon
- + Cantina Bouncer [SOR/202] — Cunning · Uncommon
- + Cargo Juggernaut [SOR/068] — Vigilance · Common
- + Clone Pilot [JTL/108] — Command · Common
- + Cobb Vanth - The Marshal [SHD/115] — Command · Rare
- + Dagger Squadron Pilot [JTL/196] — Cunning/Heroism · Common
- + Echo - Restored [SHD/099] — Command/Heroism · Uncommon
- + Geonosis Patrol Fighter [TWI/215] — Cunning · Common
- + Independent Smuggler [JTL/211] — Cunning · Common
- + Jarek Yeager - Coordinating With The Resistance [JTL/109] — Command · Uncommon
- + Kanan Jarrus - Spectre One [LAW/089] — Cunning/Vigilance/Heroism · Uncommon
- + Milodon Rider [LAW/240] — Cunning · Common
- + Paige Tico - Dropping the Hammer [JTL/046] — Vigilance/Heroism · Uncommon
- + Pelta Supply Frigate [TWI/095] — Command/Heroism · Common
- + Phantom - Spectre Shuttle [LAW/144] — Command/Heroism · Rare
- + Pirated Starfighter [SOR/209] — Cunning · Uncommon
- + Point Rain Reclaimer [LOF/092] — Command/Heroism · Common
- + Qui-Gon Jinn - Influencing Chance [LAW/237] — Cunning · Rare
- + R2-D2 - Full of Solutions [TWI/193] — Cunning/Heroism · Uncommon
- + Rio Durant - Beckett's Right Hands [LAW/093] — Cunning/Vigilance · Rare
- + Rogue Squadron Skirmisher [SOR/101] — Command/Heroism · Uncommon
- + Subjugating Starfighter [TWI/112] — Command · Common
- + Trade Federation Shuttle [TWI/060] — Vigilance · Common
- + Tranquility - Inspiring Flagship [TWI/246] — Heroism · Rare
- + Vanguard Ace [SOR/191] — Cunning/Heroism · Uncommon

*Events (5)*
- + Direct Hit [JTL/078] — Vigilance · Common
- + Electromagnetic Pulse [JTL/230] — Cunning · Common
- + Fly Casual [JTL/206] — Cunning/Heroism · Uncommon
- + Punch It [JTL/231] — Cunning · Common
- + Salvage [JTL/121] — Command · Uncommon

**Removed (33)**

*Units (28)*
- − Anakin Skywalker - Force Prodigy [LOF/190] — Cunning/Heroism · Special
- − Bunker Defender [JTL/107] — Command · Common
- − Charging Phillak [LOF/210] — Cunning · Common
- − Chirrut Îmwe - Blind, but not Deaf [LOF/067] — Vigilance · Uncommon
- − Dagoyan Master [LOF/115] — Command · Uncommon
- − Depa Billaba - A Higher Purpose [LOF/199] — Cunning/Heroism · Uncommon
- − Fireball - An Explosion With Wings [JTL/198] — Cunning/Heroism · Uncommon
- − General Draven - Doing What Must Be Done [JTL/117] — Command · Rare
- − Graceful Purrgil [LOF/069] — Vigilance · Common
- − Guerilla Soldier [JTL/218] — Cunning · Common
- − Han Solo - Has His Moments [JTL/203] — Cunning/Heroism · Legendary
- − Jedi Sentinel [LOF/196] — Cunning/Heroism · Common
- − Jedi Temple Guards [LOF/113] — Command · Common
- − Kelleran Beq - The Sabered Hand [LOF/100] — Command/Heroism · Uncommon
- − Maz Kanata - The Light Guides [LOF/111] — Command · Uncommon
- − Obi-Wan Kenobi - Protective Padawan [LOF/096] — Command/Heroism · Special
- − Priestesses of the Force - Eternal [LOF/072] — Vigilance · Uncommon
- − Qui-Gon Jinn - The Negotiations will be Short [LOF/200] — Cunning/Heroism · Legendary
- − R2-D2 - Artooooooooo! [JTL/245] — Heroism · Uncommon
- − Radiant VII - Ambassadors' Arrival [JTL/226] — Cunning · Legendary
- − Rafa Martez - Shrewd Sister [JTL/219] — Cunning · Uncommon
- − Tantive IV - Fleeing the Empire [JTL/252] — Heroism · Uncommon
- − The Legacy Run - Doomed Debris [LOF/213] — Cunning · Legendary
- − The Mandalorian - Weathered Pilot [JTL/210] — Cunning · Uncommon
- − Tri-Droid Suppressor [TWI/217] — Cunning · Common
- − Tusken Tracker [LOF/209] — Cunning · Common
- − Village Tender [LOF/107] — Command · Common
- − Wing Guard Security Team [JTL/072] — Vigilance · Uncommon

*Events (5)*
- − Following the Path [LOF/103] — Command/Heroism · Common
- − Mind Trick [LOF/704] — Cunning/Heroism · Rare
- − Overpower [LOF/126] — Command · Common
- − Premonition of Doom [LOF/203] — Cunning/Heroism · Rare
- − Timely Reinforcements [JTL/130] — Command · Uncommon

## Notes

- **Playable now** — every card is owned (collection-aware build). For the theoretical best-case (full card pool) version and the ranked pickup list to upgrade toward it, see the Desktop acquisition tier list.
- **Engine:** Qui-Gon's Aethersprite re-fires a When-Played; Qui-Gon's leader ability bounces a friendly unit and free-cheats a cheaper one (re-firing its When-Played); Avar + Nightsister Lair both make Force tokens to fuel the bounce. The new bounce bodies (Rio Durant, Cantina Bouncer, Pirated Starfighter, Bright Hope) give the loop multiple second-fire engines.
- **Bounce package now in-deck** — the prior "top acquisition" cards (Rio Durant, Cantina Bouncer) are now fielded. Remaining bounce pickup still on the list: **Wolf Pack Escort** (TWI, cost-1 free-cheat target) — not yet owned.
- Still a heavy vehicle/pilot lean (29 Vehicle, Piloting 13) — collection-driven; the full-pool version trades these for more Jedi/Force payoffs.
