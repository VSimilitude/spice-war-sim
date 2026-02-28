from __future__ import annotations

from abc import ABC, abstractmethod

from spice_war.utils.data_structures import GameState


class BattleModel(ABC):
    @abstractmethod
    def generate_targets(
        self,
        state: GameState,
        bracket_attackers: list,
        bracket_defenders: list,
        bracket_number: int,
    ) -> dict[str, str]:
        ...

    @abstractmethod
    def generate_reinforcements(
        self,
        state: GameState,
        targets: dict[str, str],
        bracket_defenders: list,
        bracket_number: int,
    ) -> dict[str, str]:
        ...

    @abstractmethod
    def determine_battle_outcome(
        self,
        state: GameState,
        attackers: list,
        defenders: list,
        day: str,
    ) -> tuple[str, dict[str, float]]:
        ...

    @abstractmethod
    def determine_damage_splits(
        self,
        state: GameState,
        attackers: list,
        primary_defender,
    ) -> dict[str, float]:
        ...
