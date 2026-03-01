# Custom Battle Outcome — Requirements

## Goal

Allow model configs to specify a **custom** battle outcome with an arbitrary theft
percentage, bypassing the fixed full_success / partial_success / fail formula.
This lets users model scenarios that don't fit the standard outcome tiers — e.g.,
"RAG3 steals exactly 15% from Hot" regardless of building count.

## Motivation

The current outcome system maps to fixed theft percentages:

| Outcome | Theft % |
|---------|---------|
| full_success | `buildings * 5% + 10%` (10–30%) |
| partial_success | `buildings * 5%` (0–20%) |
| fail | 0% |

These tiers are coarse. Real battles sometimes land between them — a strong
partial that takes the center but not all buildings, or a weak full that barely
clears everything. A `custom` outcome lets the user specify the exact theft
percentage.

---

## 1. Model Config Format

All three standard outcome types (`full_success`, `partial_success`, `custom`)
are optional in a matrix pairing. A pairing can use any combination — including
`custom` alone. When `full_success` is omitted, it is treated as 0 (no
`partial_success` is derived from it).

**Mixed example:**

```json
{
  "battle_outcome_matrix": {
    "wednesday": {
      "RAG3": {
        "Hot": {
          "full_success": 0.2,
          "partial_success": 0.1,
          "custom": 0.5,
          "custom_theft_percentage": 15
        }
      }
    }
  }
}
```

**Custom-only example:**

```json
{
  "battle_outcome_matrix": {
    "wednesday": {
      "RAG3": {
        "Hot": {
          "custom": 0.8,
          "custom_theft_percentage": 15
        }
      }
    }
  }
}
```

### Field definitions

| Field | Type | Description |
|-------|------|-------------|
| `full_success` | float (0–1), optional | Probability of full success outcome |
| `partial_success` | float (0–1), optional | Probability of partial success outcome |
| `custom` | float (0–1), optional | Probability of the custom outcome |
| `custom_theft_percentage` | float (0–100) | Theft percentage applied when custom outcome hits |

### Constraints

- If `custom` is present, `custom_theft_percentage` must also be present.
- `custom_theft_percentage` must be between 0 and 100 (inclusive).
- When `full_success` is omitted from a pairing that has `custom`,
  `partial_success` is **not** derived from it — both default to 0.
- Total probabilities (`full_success + partial_success + custom`) must not exceed
  1.0. Remainder is `fail`.
- The power-based heuristic fallback never produces a custom outcome — it is
  user-configured only.

### Multi-attacker handling

When multiple attackers target the same defender, `custom` probability and
`custom_theft_percentage` are averaged the same way `full_success` and
`partial_success` are. If only some attackers have a `custom` entry, those
without contribute 0 probability but don't dilute the theft percentage.

---

## 2. Output

### Stdout

```
  Battle: RAG3 vs Hot
    Outcome: custom (50%)
    Defender buildings: 4, Theft: 15%
    Transfers:
      RAG3  +   610,069
      Hot    -  610,069
```

### JSON

```json
{
  "outcome": "custom",
  "outcome_probabilities": {
    "full_success": 0.2,
    "partial_success": 0.1,
    "custom": 0.5,
    "custom_theft_percentage": 15,
    "fail": 0.2
  },
  "defender_buildings": 4,
  "theft_percentage": 15,
  "transfers": { ... }
}
```

---

## 3. Tests

| # | Test | Validates |
|---|------|-----------|
| 1 | **Custom-only pairing** | Pairing with only `custom: 1.0, custom_theft_percentage: 15` (no `full_success`) always produces `"custom"` outcome |
| 2 | **Custom theft percentage applied** | Transfers match `defender_spice * 15 / 100`, not the building-based formula |
| 3 | **Custom coexists with standard outcomes** | Matrix with `full_success: 0.3, custom: 0.5` produces both outcomes across seeds |
| 4 | **Fail is implicit remainder** | `full: 0.2, partial: 0.1, custom: 0.3` → fail probability is 0.4 |
| 5 | **Heuristic never produces custom** | Unconfigured pairing returns only full/partial/fail |
| 6 | **Multi-attacker averaging** | Two attackers with different custom configs produce averaged probability and theft % |
| 7 | **Multi-attacker partial custom** | One attacker with custom, one without → custom probability halved, theft % not diluted |
| 8 | **Validation: custom without theft %** | Config with `custom` but no `custom_theft_percentage` raises validation error |
| 9 | **Validation: probabilities exceed 1.0** | `full: 0.5, partial: 0.3, custom: 0.4` raises validation error |
| 10 | **Custom theft 0%** | `custom_theft_percentage: 0` is valid and transfers nothing |
| 11 | **Custom theft 30%** | `custom_theft_percentage: 30` is valid and matches full_success max |
| 12 | **Custom-only no derived partial** | Pairing with only `custom` does not generate a `partial_success` probability |
| 13 | **Deterministic with seed** | Same seed + custom config → same outcome sequence |

---

## 4. Non-Goals

- **Multiple custom tiers per pairing** — one custom outcome per pairing is
  sufficient. Can be extended to a list later if needed.
- **Custom outcomes in the heuristic fallback** — custom is user-configured only.
- **Custom building counts** — buildings are still derived from defender spice.
  Only the theft percentage is overridden.
