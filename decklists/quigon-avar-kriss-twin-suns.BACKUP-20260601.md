# Qui-Gon Jinn + Avar Kriss — Twin Suns (When-Played / Force value)

**Format**: Twin Suns (80-card, 1x each)
**Alignment**: Heroism
**Aspects**: Command · Cunning · Heroism · Vigilance (strictly on-aspect — no Villainy/Aggression)
**Source**: r2-d2 collection-aware brew (`only_owned`), post-engine-upgrade
**Date**: 2026-06-01
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
- Average cost: **3.42**
- Curve: 9×1 · 16×2 · 21×3 · 14×4 · 12×5 · 2×6 · 6×7+
- Aspect split: Cunning 36 · Heroism 35 · Command 26 · Vigilance 15
- Roles: board 62 · defense 29 · removal 25 · tempo 20 · cardadv 11 · basepressure 1
- Top traits: VEHICLE 23 · FORCE 20 · REBEL 15 · JEDI 12 · FIGHTER 12 · PILOT 11 · REPUBLIC 10 · FRINGE 9
- Top keywords: Sentinel 12 · Piloting 10 · Ambush 8 · Hidden 7 · Restore 7 · Shielded 4
- Synergy score (legacy heuristic): 92
- **Interaction density**: 175.4 avg/card · 2.14 per-pair

## Main Deck (80)

### Units (62)
1x Qui-Gon Jinn's Aethersprite - Guided by the Force [LOF/197] — Cunning/Heroism · Special x
1x Paladin Training Corvette [LOF/099] — Command/Heroism · Common x
1x Qui-Gon Jinn - The Negotiations will be Short [LOF/200] — Cunning/Heroism · Legendary x
1x Priestesses of the Force - Eternal [LOF/072] — Vigilance · Uncommon 
1x Tantive IV - Fleeing the Empire [JTL/252] — Heroism · Uncommon
1x Wing Guard Security Team [JTL/072] — Vigilance · Uncommon
1x Itinerant Warrior [LOF/048] — Vigilance/Heroism · Common
1x Anakin Skywalker - Force Prodigy [LOF/190] — Cunning/Heroism · Special x
1x Dooku - It is Too Late [LOF/211] — Cunning · Uncommon
1x Admiral Yularen - Fleet Coordinator [JTL/047] — Vigilance/Heroism · Rare
1x Jedi Sentinel [LOF/196] — Cunning/Heroism · Common
1x Youngling Padawan [LOF/193] — Cunning/Heroism · Common
1x Blade Squadron B-Wing [JTL/199] — Cunning/Heroism · Common
1x Refugee of The Path [LOF/242] — Heroism · Common x
1x Kimoglia Heavy Fighter [JTL/222] — Cunning · Common
1x Blue Leader - Scarif Air Support [JTL/096] — Command/Heroism · Uncommon
1x Echo Base Engineer [JTL/044] — Vigilance/Heroism · Common
1x The Mandalorian - Weathered Pilot [JTL/210] — Cunning · Uncommon
1x Resistance Blue Squadron [JTL/102] — Command/Heroism · Common
1x Oppo Rancisis - Ancient Councilor [LOF/105] — Command · Legendary
1x Guerilla Soldier [JTL/218] — Cunning · Common
1x Poe Dameron - One Hell of a a Pilot [JTL/100] — Command/Heroism · Uncommon
1x Dornean Gunship [JTL/116] — Command · Uncommon
1x Maz Kanata - The Light Guides [LOF/111] — Command · Uncommon
1x Astromech Pilot [JTL/057] — Vigilance · Uncommon
1x Tri-Droid Suppressor [TWI/217] — Cunning · Common
1x Dagoyan Master [LOF/115] — Command · Uncommon
1x Leia Organa - Pilots, To Your Stations [JTL/097] — Command/Heroism · Uncommon
1x Village Tender [LOF/107] — Command · Common
1x Han Solo - Has His Moments [JTL/203] — Cunning/Heroism · Legendary
1x Jedi Temple Guards [LOF/113] — Command · Common
1x U-Wing Lander [JTL/070] — Vigilance · Uncommon
1x BoShek - Charismatic Smuggler [JTL/215] — Cunning · Uncommon
1x Razor Crest - Ride For Hire [JTL/223] — Cunning · Uncommon
1x Sidon Ithano - The Crimson Corsair [JTL/213] — Cunning · Rare
1x Cloaked StarViper [JTL/067] — Vigilance · Common
1x Hera Syndulla - We've Lost Enough [JTL/045] — Vigilance/Heroism · Uncommon
1x Skyway Cloud Car [JTL/220] — Cunning · Common
1x Kelleran Beq - The Sabered Hand [LOF/100] — Command/Heroism · Uncommon x
1x Academy Graduate [JTL/058] — Vigilance · Common
1x Sabine's Masterpiece - Crazy Colorful [JTL/250] — Heroism · Rare
1x Depa Billaba - A Higher Purpose [LOF/199] — Cunning/Heroism · Uncommon x
1x Stinger Mantis - Where Are We Going? [LOF/198] — Cunning/Heroism · Uncommon
1x Death Space Skirmisher [JTL/217] — Cunning · Common
1x Tusken Tracker [LOF/209] — Cunning · Common
1x General Draven - Doing What Must Be Done [JTL/117] — Command · Rare
1x Dilapidated Ski Speeder [JTL/248] — Heroism · Common
1x Bunker Defender [JTL/107] — Command · Common
1x Red Squadron X-Wing [JTL/051] — Vigilance/Heroism · Common
1x Chirrut Îmwe - Blind, but not Deaf [LOF/067] — Vigilance · Uncommon
1x Charging Phillak [LOF/210] — Cunning · Common
1x Obi-Wan Kenobi - Protective Padawan [LOF/096] — Command/Heroism · Special x
1x Red Leader - Form Up [JTL/101] — Command/Heroism · Uncommon
1x Trace Martez - Trusting Sister [JTL/066] — Vigilance · Uncommon
1x J-Type Nubian Starship [LOF/194] — Cunning/Heroism · Common x
1x Luke Skywalker - You Still With Me? [JTL/592] — Command/Heroism · Rare
1x Radiant VII - Ambassadors' Arrival [JTL/226] — Cunning · Legendary
1x R2-D2 - Artooooooooo! [JTL/245] — Heroism · Uncommon
1x The Legacy Run - Doomed Debris [LOF/213] — Cunning · Legendary
1x Fireball - An Explosion With Wings [JTL/198] — Cunning/Heroism · Uncommon
1x Rafa Martez - Shrewd Sister [JTL/219] — Cunning · Uncommon
1x Graceful Purrgil [LOF/069] — Vigilance · Common

### Events (14)
1x Directed by the Force [LOF/123] — Command · Uncommon
1x Timely Reinforcements [JTL/130] — Command · Uncommon
1x The Will of the Force [LOF/227] — Cunning · Common
1x The Burden of Masters [LOF/125] — Command · Rare
1x Sweep the Area [JTL/233] — Cunning · Uncommon
1x Prepare for Takeoff [SOR/125] — Command · Uncommon
1x Mind Trick [LOF/704] — Cunning/Heroism · Rare
1x Three Lessons [LOF/225] — Cunning · Uncommon
1x A Precarious Predicament [LOF/222] — Cunning · Uncommon
1x Following the Path [LOF/103] — Command/Heroism · Common
1x Premonition of Doom [LOF/203] — Cunning/Heroism · Rare
1x Sneak Attack [SOR/219] — Cunning · Rare
1x Overpower [LOF/126] — Command · Common
1x Focus Fire [JTL/129] — Command · Common

### Upgrades (4)
1x Qui-Gon Jinn's Lightsaber [LOF/201] — Cunning/Heroism · Special
1x Heirloom Lightsaber [LOF/053] — Vigilance/Heroism · Common
1x Pillio Star Compass [LOF/122] — Command · Uncommon
1x Ascension Cable [LOF/215] — Cunning · Common

## Notes

- **Playable now** — every card is owned (collection-aware build). For the theoretical best-case (full card pool) version and the ranked pickup list to upgrade toward it, see the Desktop acquisition tier list.
- **Engine:** Qui-Gon's Aethersprite re-fires a When-Played; Qui-Gon's leader ability bounces a friendly unit and free-cheats a cheaper one (re-firing its When-Played); Avar + Nightsister Lair both make Force tokens to fuel the bounce.
- **Top acquisition to tighten the bounce loop:** Rio Durant – Beckett's Right Hands (LAW/093, unit), then Wolf Pack Escort, Cantina Bouncer.
- Still a vehicle/pilot lean (23 Vehicle) — collection-driven; the full-pool version trades these for more Jedi/Force payoffs.
