# State File Format

How to capture a real-world Spice Wars game state as a JSON file the simulator can consume.

## Top-Level Structure

```json
{
  "alliances": [ ... ],
  "event_schedule": [ ... ]
}
```

Both keys are required. No other top-level keys are allowed.

---

## `alliances`

An array of alliance objects. Must contain at least one alliance from each of two factions.

### Required Fields

| Field | Type | Description |
|---|---|---|
| `alliance_id` | string | Unique identifier for the alliance. Used everywhere else in the system to reference this alliance. Pick something short and recognizable (e.g. `"S12_TopDogs"`). |
| `faction` | string | Which faction this alliance belongs to (e.g. `"red"`, `"blue"`). Exactly two distinct faction values must appear across all alliances. |
| `power` | number | The alliance's total power rating. Determines battle outcomes. Use whatever scale the game reports — the simulator only cares about relative values between alliances. |
| `starting_spice` | integer | How much spice this alliance has right now. If entering state at the start of the war, use the initial spice amount. If entering mid-war, use the alliance's current spice total. |
| `daily_rate` | integer | Spice earned per day from passive land control. Typically around 30,000–50,000 but varies by alliance. |

### Optional Fields

| Field | Type | Description |
|---|---|---|
| `name` | string | Human-readable display name (e.g. `"The Top Dogs"`). For your reference only — not used in calculations. |
| `server` | string | Which server this alliance is on (e.g. `"S12"`). For your reference only — not used in calculations. |

### Example Alliance

```json
{
  "alliance_id": "S12_TopDogs",
  "faction": "red",
  "power": 110,
  "starting_spice": 2000000,
  "daily_rate": 50000,
  "name": "The Top Dogs",
  "server": "S12"
}
```

### Notes

- **`alliance_id` must be unique** across all alliances in the file.
- **Exactly two factions.** Every alliance must belong to one of exactly two factions. The faction strings can be anything (`"red"`/`"blue"`, `"north"`/`"south"`, etc.) as long as there are exactly two distinct values.
- **Power is relative.** An alliance with power 110 vs one with power 55 is twice as strong. The absolute numbers don't matter, only the ratios.
- **`starting_spice` drives buildings.** The simulator uses this value to determine how many side buildings an alliance has at the first event:
  - 0 buildings: < 150k
  - 1 building: 150k–705k
  - 2 buildings: 705k–1,805k
  - 3 buildings: 1,805k–3,165k
  - 4 buildings: >= 3,165k

---

## `event_schedule`

An array of event objects, one per battle event, in chronological order. A standard 4-week war has 8 events (Wednesday + Saturday each week).

### Required Fields

| Field | Type | Description |
|---|---|---|
| `attacker_faction` | string | Which faction attacks in this event. Must match a faction string used in `alliances`. |
| `day` | string | Day of the week this event falls on (e.g. `"wednesday"`, `"saturday"`). Used to calculate how many days of passive spice accumulate between events. |
| `days_before` | integer | Number of days between this event and the previous one (or from war start to the first event). Used to calculate passive spice earned between events. |

### Example Event Schedule

A standard 8-event war with alternating attackers:

```json
[
  {"attacker_faction": "red",  "day": "wednesday", "days_before": 3},
  {"attacker_faction": "blue", "day": "saturday",  "days_before": 3},
  {"attacker_faction": "red",  "day": "wednesday", "days_before": 4},
  {"attacker_faction": "blue", "day": "saturday",  "days_before": 3},
  {"attacker_faction": "red",  "day": "wednesday", "days_before": 4},
  {"attacker_faction": "blue", "day": "saturday",  "days_before": 3},
  {"attacker_faction": "red",  "day": "wednesday", "days_before": 4},
  {"attacker_faction": "blue", "day": "saturday",  "days_before": 3}
]
```

### Notes

- **`days_before` for the first event** is the number of days from the war start to the first battle. During this time alliances accumulate spice passively.
- **Every faction referenced** in the schedule must have at least one alliance in the `alliances` array.
- The defender for each event is implicitly the other faction.

---

## Full Example

A minimal but complete state file with 4 alliances and 2 events:

```json
{
  "alliances": [
    {
      "alliance_id": "RedWolves",
      "faction": "red",
      "power": 110,
      "starting_spice": 2000000,
      "daily_rate": 50000
    },
    {
      "alliance_id": "RedFalcons",
      "faction": "red",
      "power": 85,
      "starting_spice": 1500000,
      "daily_rate": 40000
    },
    {
      "alliance_id": "BlueLions",
      "faction": "blue",
      "power": 95,
      "starting_spice": 1800000,
      "daily_rate": 45000
    },
    {
      "alliance_id": "BlueShields",
      "faction": "blue",
      "power": 70,
      "starting_spice": 900000,
      "daily_rate": 30000
    }
  ],
  "event_schedule": [
    {"attacker_faction": "red",  "day": "wednesday", "days_before": 3},
    {"attacker_faction": "blue", "day": "saturday",  "days_before": 3}
  ]
}
```

---

## Gathering the Data

A checklist for translating a real game into this format:

1. **List every alliance** participating in the war from both factions. You need all of them — the simulator brackets alliances by rank within each faction, so missing alliances will skew the brackets.

2. **For each alliance, record:**
   - A unique ID you'll use to refer to it
   - Which faction it's in
   - Its current power rating
   - Its current spice total (or starting spice if the war hasn't begun)
   - Its approximate daily spice income from land

3. **Map out the event schedule.** For each of the 8 battle events:
   - Which faction is attacking
   - What day of the week it falls on
   - How many days since the last event (or war start)

4. **If entering mid-war state:** Use current spice totals as `starting_spice` and only include the remaining events in `event_schedule`. The simulator will run forward from whatever point you give it.
