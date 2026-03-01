# Expected Value Targeting — Requirements

## Goal

Add a new default targeting heuristic that maximizes **expected spice gain** —
each attacker picks the unassigned defender that yields the highest expected
stolen spice, considering both probability of success and the amount available
to steal. The original heuristic remains available as a config option.

## Motivation

The current default targeting sorts attackers by power and defenders by current
spice, then assigns 1:1 in order. This is a rough proxy but ignores the
attacker's actual probability of succeeding against each defender. A weak
attacker assigned to a rich-but-strong defender may have near-zero expected
return, while a weaker defender with slightly less spice could be a much better
target.

**Example:** Attacker (12B power) choosing between:
- Defender X: 18B power, 3M spice — ~7% partial chance → ESV ≈ 4,200
- Defender Y: 10B power, 2M spice — ~100% full chance → ESV ≈ 600,000

The current heuristic picks X (more spice). The new heuristic picks Y (more
expected spice).

### Ranking rivalry as a non-goal for the heuristic

In practice, only the top alliance from each faction cares about targeting a
specific rival to protect their final ranking — and that decision depends on
meta-knowledge the heuristic can't capture (diplomacy, event history,
remaining schedule). Rather than adding complexity to the algorithm, users
handle this via target overrides (see Section 2).

---

## 1. Behavioral Rules

### Expected Spice Value (ESV)

For a given attacker-defender pairing, ESV is the sum of each possible
outcome's probability multiplied by the spice that outcome would steal.
Probabilities come from the same lookup path the battle uses (matrix entry if
configured, power-based heuristic fallback otherwise). Theft amounts use the
existing building count and theft percentage calculations. Custom outcomes are
included when a matrix entry defines them.

### Priority order

Attackers choose targets in descending power order. The strongest attacker
picks first from all available defenders, then the next strongest picks from
the remaining defenders, and so on.

### Tie-breaking

When two unassigned defenders have equal ESV for an attacker, break ties by:
1. Higher current spice
2. Alphabetical alliance_id (deterministic fallback)

### Reinforcement logic

Unchanged — reinforcements still follow the existing most-attacked rule.

---

## 2. Configuration

### 2.1 Global Targeting Strategy

A `targeting_strategy` config field selects the default algorithm for
attackers with no override:

```json
{
  "targeting_strategy": "expected_value"
}
```

| Value | Behavior |
|-------|----------|
| `"expected_value"` | New ESV-maximizing heuristic (default) |
| `"highest_spice"` | Original heuristic (sort by power/spice, assign 1:1) |

Default: `"expected_value"` when omitted.

### 2.2 Global and Per-Event Target Overrides

Targets can be configured at two levels. Each alliance entry is a dict with
exactly one key — either `"target"` (pin to a specific defender) or
`"strategy"` (use a named algorithm for this alliance).

**Global defaults** — apply to every event unless overridden:

```json
{
  "default_targets": {
    "RAG3": {"target": "Hot"},
    "Blue1": {"strategy": "highest_spice"},
    "Blue2": {"strategy": "expected_value"}
  }
}
```

**Per-event overrides** — apply to a single event (existing `event_targets`):

```json
{
  "event_targets": {
    "3": {
      "RAG3": {"target": "Weak1"},
      "Blue1": {"target": "Hot"}
    }
  }
}
```

### 2.3 Resolution Order

For each attacker in a given event, resolve target in this order:

1. **`event_targets[event_number][attacker_id]`** — most specific, wins if present
2. **`default_targets[attacker_id]`** — global per-alliance config
3. **`targeting_strategy`** — global default algorithm

At each level, a `{"strategy": "..."}` entry selects the algorithm for that
alliance rather than pinning a defender. This allows per-alliance strategy
selection — e.g., most alliances use ESV but one uses `highest_spice`.

A `{"strategy": "..."}` entry in `event_targets` overrides a `{"target": "..."}`
pin in `default_targets`, letting an alliance use the algorithm for just that
event.

Pinned targets are resolved before algorithms run. Algorithms only assign
from defenders not already claimed by pins. If a pinned defender is not in
the current bracket (wrong faction, etc.), the pin is ignored for that event
and the attacker falls through to the next resolution level.

### 2.4 Example Configs

**Minimal — just use the new algorithm:**
```json
{}
```

**Top alliance pinned, one alliance uses old heuristic, rest use default:**
```json
{
  "default_targets": {
    "RAG3": {"target": "Hot"},
    "Blue1": {"strategy": "highest_spice"}
  }
}
```

**Pin globally but override one event:**
```json
{
  "default_targets": {
    "RAG3": {"target": "Hot"}
  },
  "event_targets": {
    "5": {
      "RAG3": {"strategy": "expected_value"}
    }
  }
}
```

**Old behavior for users who prefer it:**
```json
{
  "targeting_strategy": "highest_spice"
}
```

---

## 3. Tests

### ESV Algorithm

| # | Test | Validates |
|---|------|-----------|
| 1 | **Weak attacker avoids strong defender** | Attacker with low power ratio vs rich-but-strong defender picks weaker-but-beatable defender instead |
| 2 | **Strong attacker picks richest viable target** | Attacker who can beat everyone picks the richest defender (same as old behavior for dominant attackers) |
| 3 | **Equal-power bracket** | When all power ratios are similar, falls back to highest-spice ordering (approximates old behavior) |
| 4 | **ESV calculation correctness** | Known inputs → exact ESV output matching the formula |
| 5 | **Building count affects ESV** | Defender at 3.2M spice (4 buildings, 30% full theft) is more attractive than defender at 600K spice (1 building, 15% full theft), all else equal |
| 6 | **Priority order respected** | Highest-power attacker gets first pick; second attacker chooses from remaining |
| 7 | **Tie-breaking by spice then id** | Two defenders with identical ESV — higher spice wins; if spice also ties, alphabetical id wins |
| 8 | **Matrix probabilities used when available** | If battle_outcome_matrix has an entry for a pairing, ESV uses those probabilities instead of heuristic |
| 9 | **Custom outcome included in ESV** | Matrix entry with custom outcome contributes to ESV calculation |
| 10 | **Single attacker, single defender** | Trivial case — only one option, assigned regardless of ESV |
| 11 | **All defenders too strong** | All ESVs are 0 (100% fail probability) — still assigns targets (ties broken by spice) |

### Configuration & Resolution

| # | Test | Validates |
|---|------|-----------|
| 12 | **targeting_strategy: highest_spice** | Setting `"highest_spice"` uses original heuristic (sort by power/spice) |
| 13 | **targeting_strategy: expected_value** | Explicit `"expected_value"` behaves same as default (omitted) |
| 14 | **default_targets fixed pin** | `{"target": "Hot"}` in default_targets → RAG3 targets Hot in every event |
| 15 | **default_targets per-alliance strategy** | `{"strategy": "highest_spice"}` in default_targets → that alliance uses old heuristic while others use default |
| 16 | **event_targets overrides default_targets pin** | default_targets pins RAG3→Hot, but event_targets for event 3 pins RAG3→Weak1 → event 3 uses Weak1 |
| 17 | **event_targets strategy overrides default pin** | default_targets pins RAG3→Hot, event_targets has `{"strategy": "expected_value"}` → RAG3 uses algorithm for that event |
| 18 | **Pinned target not in bracket** | default_targets pins RAG3→Hot, but Hot is not a defender this event → pin ignored, RAG3 falls through to algorithm |
| 19 | **Pins resolved before algorithm** | Two pinned attackers take their defenders; algorithm assigns remaining attackers from remaining defenders only |
| 20 | **Partial event_targets + default_targets** | Mix of global pins, per-alliance strategies, per-event overrides, and global fallback all coexist correctly |
| 21 | **Invalid targeting_strategy** | Unrecognized strategy value raises validation error |
| 22 | **Invalid override dict** | Override with neither `"target"` nor `"strategy"` key raises validation error |

---

## 4. Non-Goals

- **Multi-event lookahead** — the algorithm considers only current state (spice,
  power, day). Future event reasoning is out of scope.
- **Ranking-aware targeting** — handled by user via `default_targets` /
  `event_targets` overrides.
- **Changes to reinforcement logic** — reinforcements remain unchanged.
- **Changes to battle outcome or damage split models** — this only affects
  target selection.
