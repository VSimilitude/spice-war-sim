# Game Mechanics Specification

## Overview
This specification covers the mechanics for "Spice Wars" - a recurring event in a multi-player mobile war game. The focus is on modeling alliance-based warfare within a faction system that groups servers together.

## Game Entities

### Players
- Each player has a **power level** (numeric value representing strength)
- Players are permanently assigned to a **server** (no transfers between servers)
- Players join **alliances** within their server
- Players can freely move between alliances on their server (in practice, movement is rare)

### Servers
- Independent game instances with separate player populations
- Each server contains multiple alliances
- Typical server composition:
  - **1-5 top alliances**: 90-100 players each, high power
  - **5-10 lower alliances**: 50-100 players each, lower power
- 4 servers are grouped together into a **faction** for Spice Wars events

### Alliances
- Groups of players working together (max 100 members)
- Formed within a single server
- Alliance size: typically 50-100 players
- Alliance priorities:
  1. Alliance success (primary)
  2. Server success (secondary)

### Factions
- A grouping of exactly **4 servers**
- Determines attack eligibility rules for Spice Wars
- Players can only attack targets within their faction (cross-server within the faction)
- Two factions compete against each other in Spice Wars

## Resource Management

### Spice
- **Primary resource** being competed for in Spice Wars
- Alliances accumulate spice through two mechanisms:
  1. **Passive generation**: Land control within own server (~50k spice/day per alliance, varies slightly)
  2. **Active theft**: Stealing from enemy faction alliances during battle events

### Spice Generation
- Based on land control within alliance's home server
- Amount varies by alliance based on land quality/quantity
- Diplomatic arrangement within server (all alliances on same server are allied)
- Cannot be attacked by foreign servers for land control
- Approximate rate: **~50,000 spice per day** (varies by alliance)

## Events

### Spice Wars Event Structure
- **Duration**: 4 weeks total (28 days)
- **Battle Events**: Twice weekly (Wednesday and Saturday) = 8 total battle events
- **Two Factions**: Competing against each other
- **Attacker/Defender Roles**: Alternate between factions based on schedule
  - Each faction attacks **4 times** total: twice on Wednesday and twice on Saturday
  - This ensures neither faction has a day-of-week advantage (Wednesday battles are easier for attackers than Saturday)
  - Standard 8-event schedule (A/B = the two factions):

    | Event | Attacker | Day |
    |-------|----------|-----|
    | 1 | A | Wednesday |
    | 2 | B | Saturday |
    | 3 | B | Wednesday |
    | 4 | A | Saturday |
    | 5 | B | Wednesday |
    | 6 | A | Saturday |
    | 7 | A | Wednesday |
    | 8 | B | Saturday |

### Initial Conditions
- **Starting spice**: Each alliance begins with a **configurable** initial spice amount
  - May vary by scenario, season, or testing purposes
  - Typically alliances start with some base amount (not zero)
- Initial spice affects early bracketing and side building counts

### Battle Event Flow
Each battle event consists of two atomic stages:

**Stage 1: Bracketing and Target Declaration**
- Bracketing is locked in based on current spice rankings within each faction
- Attacking faction alliances declare their targets from defending faction
- Brackets are groups of 10 by rank (1-10, 11-20, 21-30, etc.)
- Alliances can only target enemies in the same bracket
- Top ~2 brackets (1-10, 11-20) are most relevant

**Stage 2: Battle Resolution**
- All battles happen simultaneously
- Spice theft occurs based on battle outcomes
- Results distributed to all participants

### Battle Mechanics

#### Defense Structures
Each defending alliance has:
- **1 Main Alliance Center**: Worth 10% of defender's spice if destroyed
- **0-4 Side Buildings**: Worth 5% each if destroyed (easier to destroy than center)
- **Maximum possible theft**: 30% of defender's spice (4 buildings × 5% + center 10%)

**Side Building Count Thresholds:**
Number of side buildings depends on defender's spice total at bracket lock-in time:
- **0 buildings**: < 150k spice
- **1 building**: 150k - 705k spice
- **2 buildings**: 705k - 1,805k spice
- **3 buildings**: 1,805k - 3,165k spice
- **4 buildings**: ≥ 3,165k spice

#### Attack Rules
- Each attacking alliance **must** target exactly one defending alliance per event
- Multiple attackers (up to 3) can target the same defender
- Attackers must be in same bracket as defender (by rank within faction)
- No penalty for unsuccessful attacks (attacker risks nothing)
- **For modeling purposes**: Assume all attacking alliances participate in each battle event

#### Defense Reinforcement Rules
- When multiple attackers (2-3) target the same defending alliance, other defending alliances in that bracket may go un-targeted
- Un-targeted defending alliances **join the defense** of a targeted alliance
- Each un-targeted defender reinforces exactly one battle
- Maximum **additional** reinforcements = number of attackers - 1
  - Example: If alliances A, B, C (3 attackers) attack alliance X, then up to 2 un-targeted defenders (Y, Z) join X's defense
  - This creates a balanced battle: 3 attackers vs 3 total defenders (X + Y + Z)
- Reinforcing defenders contribute their power to the defense side of the battle
- **Only the primary targeted defender (X in the example) loses spice if attackers succeed** - reinforcing defenders risk nothing
- **For modeling purposes**: Assume all un-targeted defenders participate in reinforcement (fill available slots)

#### Spice Distribution
- Total spice stolen = percentage based on buildings/center destroyed (0-30%)
- If multiple attackers on same target:
  - Total stolen amount stays the same (still capped at 30%)
  - Divided among attackers based on damage contribution
  - Example: 3 attackers destroy all buildings (30% total), spice split based on each attacker's damage dealt
  - **Damage contribution modeling**: See [model_generation.md](model_generation.md) for how damage is calculated and distributed

#### Battle Outcome Factors
Battle success (which buildings get destroyed) depends on:
- Relative power between attacker(s) and defender
- Number of active participants
- Specific battle mechanics (to be modeled with simplified heuristics)

### Event Impact
- Alliance spice totals change based on theft/defense
- Rankings within faction shift based on new spice totals
- Bracket assignments may change for next battle event (dynamic)

## Win/Loss Conditions

### Event-Level Success Tiers
Based on final alliance spice total at end of 4-week event:
- **Tier 1**: Rank 1st
- **Tier 2**: Rank 2nd-3rd
- **Tier 3**: Rank 4th-10th
- **Tier 4**: Rank 11th-20th
- **Tier 5**: Rank 21st and below

Rankings are compared across all alliances in the event (across both factions).
