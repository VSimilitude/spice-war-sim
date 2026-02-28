from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Alliance:
    alliance_id: str
    faction: str
    power: float
    starting_spice: int
    daily_spice_rate: int
    name: str | None = None
    server: str | None = None
    damage_weight: float | None = None


@dataclass
class EventConfig:
    attacker_faction: str
    day: str
    days_before: int


@dataclass
class GameState:
    current_spice: dict[str, int]
    brackets: dict[str, int]
    event_number: int
    day: str
    event_history: list[dict]
    alliances: list[Alliance]
