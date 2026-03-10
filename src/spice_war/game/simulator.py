from __future__ import annotations

from spice_war.game.events import coordinate_event
from spice_war.game.mechanics import calculate_final_rankings
from spice_war.models.base import BattleModel
from spice_war.utils.data_structures import Alliance, EventConfig, GameState


def process_between_events(
    current_spice: dict[str, int],
    days_elapsed: int,
    daily_rates: dict[str, int],
) -> dict[str, int]:
    updated = dict(current_spice)
    for aid, rate in daily_rates.items():
        updated[aid] += rate * days_elapsed
    return updated


def simulate_war(
    alliances: list[Alliance],
    event_schedule: list[EventConfig],
    model: BattleModel,
) -> dict:
    current_spice = {a.alliance_id: a.starting_spice for a in alliances}
    daily_rates = {a.alliance_id: a.daily_spice_rate for a in alliances}
    event_history = []

    for event_number, event_config in enumerate(event_schedule, start=1):
        # Apply passive income before event
        current_spice = process_between_events(
            current_spice, event_config.days_before, daily_rates
        )
        spice_before = dict(current_spice)

        state = GameState(
            current_spice=current_spice,
            brackets={},
            event_number=event_number,
            day=event_config.day,
            event_history=event_history,
            alliances=alliances,
            event_schedule=event_schedule,
        )

        if hasattr(model, "set_effective_powers"):
            model.set_effective_powers()

        updated_spice, event_info = coordinate_event(
            state,
            event_config.attacker_faction,
            event_config.day,
            event_number,
            model,
        )

        current_spice = updated_spice
        event_info["days_before"] = event_config.days_before
        event_info["spice_before"] = spice_before
        event_info["spice_after"] = dict(current_spice)
        event_history.append(event_info)

    rankings = calculate_final_rankings(alliances, current_spice)

    return {
        "final_spice": current_spice,
        "rankings": rankings,
        "event_history": event_history,
    }
