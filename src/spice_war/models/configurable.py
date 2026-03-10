from __future__ import annotations

import math
import random
from collections import Counter

from spice_war.game.mechanics import calculate_building_count, calculate_theft_percentage
from spice_war.models.base import BattleModel
from spice_war.utils.data_structures import Alliance, EventConfig, GameState


def heuristic_from_ratio(ratio: float, day: str) -> dict[str, float]:
    """Compute heuristic battle probabilities from a power ratio and day."""
    if day == "wednesday":
        full = max(0.0, min(1.0, 1.35 * ratio - 0.95))
        cumulative_partial = max(0.0, min(1.0, 1.9 * ratio - 1.35))
    else:  # saturday
        full = max(0.0, min(1.0, 1.65 * ratio - 1.10))
        cumulative_partial = max(0.0, min(1.0, 1.65 * ratio - 0.85))

    partial = max(0.0, cumulative_partial - full)
    return {"full_success": full, "partial_success": partial}


class ConfigurableModel(BattleModel):
    def __init__(self, config: dict, alliances: list[Alliance]):
        self.config = config
        self.alliances = {a.alliance_id: a for a in alliances}
        seed = config.get("random_seed", 0)
        self.rng = random.Random(seed)

        # MC randomness parameters
        self.targeting_temperature = config.get("targeting_temperature", 0.0)
        self.power_noise = config.get("power_noise", 0.0)
        self.outcome_noise = config.get("outcome_noise", 0.0)

        # Pre-generate per-pairing outcome offsets (deterministic from seed)
        self._pairing_offsets: dict[tuple[str, str], dict[str, float]] = {}
        if self.outcome_noise > 0:
            self._generate_pairing_offsets()

        # Per-event effective powers (populated via set_effective_powers)
        self._effective_powers: dict[str, float] = {}

    def _generate_pairing_offsets(self) -> None:
        seed = self.config.get("random_seed", 0)
        offset_rng = random.Random(seed + 1_000_000)
        noise = self.outcome_noise
        alliance_ids = sorted(self.alliances.keys())
        for att_id in alliance_ids:
            for def_id in alliance_ids:
                if att_id == def_id:
                    continue
                self._pairing_offsets[(att_id, def_id)] = {
                    "full_success": offset_rng.uniform(-noise, noise),
                    "partial_success": offset_rng.uniform(-noise, noise),
                    "custom": offset_rng.uniform(-noise, noise),
                }

    def set_effective_powers(self) -> None:
        if self.power_noise <= 0:
            self._effective_powers = {
                aid: a.power for aid, a in self.alliances.items()
            }
            return
        noise = self.power_noise
        self._effective_powers = {}
        for aid in sorted(self.alliances.keys()):
            base = self.alliances[aid].power
            u = self.rng.uniform(-noise, noise)
            self._effective_powers[aid] = base * (1 + u)

    def _get_power(self, alliance_id: str) -> float:
        return self._effective_powers.get(
            alliance_id, self.alliances[alliance_id].power
        )

    # ── M1: Targeting ──────────────────────────────────────────────

    def generate_targets(
        self,
        state: GameState,
        bracket_attackers: list[Alliance],
        bracket_defenders: list[Alliance],
        bracket_number: int,
    ) -> dict[str, str]:
        event_targets_config = self.config.get("event_targets", {})
        default_targets_config = self.config.get("default_targets", {})
        global_strategy = self.config.get("targeting_strategy", "expected_value")

        event_key = str(state.event_number)
        event_overrides = event_targets_config.get(event_key, {})

        defender_ids = {d.alliance_id for d in bracket_defenders}

        # Phase 1: Resolve pinned targets
        pins: dict[str, str] = {}
        algo_attackers: list[tuple[Alliance, str]] = []

        for attacker in bracket_attackers:
            aid = attacker.alliance_id
            resolved_target, resolved_strategy = self._resolve_attacker(
                aid, event_overrides, default_targets_config, global_strategy,
                defender_ids,
            )
            if resolved_target is not None:
                pins[aid] = resolved_target
            else:
                algo_attackers.append((attacker, resolved_strategy))

        # Phase 2: Split algo_attackers into priority + regular groups
        targets = dict(pins)
        assigned: set[str] = set(pins.values())

        priority_attackers: list[Alliance] = []
        regular_attackers: list[tuple[Alliance, str]] = []

        has_maximize_tier = any(
            s == "maximize_tier" for _, s in algo_attackers
        )

        if has_maximize_tier:
            attacking_faction = bracket_attackers[0].faction
            top_n_ids = self._get_top_n_ids(state, attacking_faction)
            fallback = self.config.get(
                "tier_optimization_fallback", "rank_aware"
            )
            for attacker, strategy in algo_attackers:
                if strategy == "maximize_tier" \
                        and attacker.alliance_id in top_n_ids:
                    priority_attackers.append(attacker)
                else:
                    effective = fallback if strategy == "maximize_tier" \
                        else strategy
                    regular_attackers.append((attacker, effective))
        else:
            regular_attackers = list(algo_attackers)

        # Priority group picks first (forward sim, by power desc)
        priority_attackers.sort(
            key=lambda a: self._get_power(a.alliance_id), reverse=True
        )
        for attacker in priority_attackers:
            available = [
                d for d in bracket_defenders
                if d.alliance_id not in assigned
            ]
            if not available:
                break
            best = self._pick_maximize_tier_target(attacker, available, state)
            targets[attacker.alliance_id] = best.alliance_id
            assigned.add(best.alliance_id)

        # Regular group picks next (by power desc)
        regular_attackers.sort(
            key=lambda pair: self._get_power(pair[0].alliance_id),
            reverse=True,
        )
        for attacker, strategy in regular_attackers:
            available = [
                d for d in bracket_defenders
                if d.alliance_id not in assigned
            ]
            if not available:
                break
            best = self._pick_by_strategy(attacker, available, state, strategy)
            targets[attacker.alliance_id] = best.alliance_id
            assigned.add(best.alliance_id)

        return targets

    def _resolve_attacker(
        self,
        attacker_id: str,
        event_overrides: dict,
        default_targets_config: dict,
        global_strategy: str,
        defender_ids: set[str],
    ) -> tuple[str | None, str]:
        """Returns (pinned_target_or_None, strategy)."""
        # Level 1: event_targets override
        if attacker_id in event_overrides:
            entry = event_overrides[attacker_id]
            target, strategy = self._parse_override(entry)
            if target is not None:
                if target in defender_ids:
                    return target, ""
                # Pin invalid for this bracket — fall through to level 2
            else:
                return None, strategy

        # Level 2: default_targets
        if attacker_id in default_targets_config:
            entry = default_targets_config[attacker_id]
            target, strategy = self._parse_override(entry)
            if target is not None:
                if target in defender_ids:
                    return target, ""
                # Pin invalid for this bracket — fall through to level 3
            else:
                return None, strategy

        # Level 3: faction_targeting_strategy
        faction_strategy = self.config.get("faction_targeting_strategy", {})
        attacker = self.alliances.get(attacker_id)
        if attacker and attacker.faction in faction_strategy:
            return None, faction_strategy[attacker.faction]

        # Level 4: global strategy
        return None, global_strategy

    def _parse_override(self, entry) -> tuple[str | None, str]:
        """Parse an override entry (string or dict) into (target, strategy)."""
        if isinstance(entry, str):
            return entry, ""
        if "target" in entry:
            return entry["target"], ""
        return None, entry["strategy"]

    def _calculate_esv(
        self,
        attacker: Alliance,
        defender: Alliance,
        state: GameState,
    ) -> float:
        matrix = self.config.get("battle_outcome_matrix", {})
        probs = self._lookup_or_heuristic(matrix, attacker, defender, state.day)

        if self.outcome_noise > 0:
            probs = self._apply_outcome_noise(
                probs, attacker.alliance_id, defender.alliance_id
            )

        defender_spice = state.current_spice[defender.alliance_id]
        building_count = calculate_building_count(defender_spice)

        esv = 0.0

        full_prob = probs.get("full_success", 0.0)
        if full_prob > 0:
            theft_pct = calculate_theft_percentage("full_success", building_count)
            esv += full_prob * (defender_spice * theft_pct / 100.0)

        partial_prob = probs.get("partial_success", 0.0)
        if partial_prob > 0:
            theft_pct = calculate_theft_percentage("partial_success", building_count)
            esv += partial_prob * (defender_spice * theft_pct / 100.0)

        custom_prob = probs.get("custom", 0.0)
        if custom_prob > 0:
            custom_theft_pct = probs.get("custom_theft_percentage", 0.0)
            esv += custom_prob * (defender_spice * custom_theft_pct / 100.0)

        return esv

    def _softmax_select(
        self,
        candidates: list[Alliance],
        scores: dict[str, float],
    ) -> Alliance:
        if len(candidates) == 1:
            return candidates[0]

        T = self.targeting_temperature

        # Normalize scores to 0–1 range
        raw = [scores.get(c.alliance_id, 0.0) for c in candidates]
        s_max = max(raw)
        if s_max > 0:
            normalized = [s / s_max for s in raw]
        else:
            # All zero — uniform selection
            return self.rng.choice(candidates)

        # Softmax with overflow protection
        n_max = max(normalized)
        exp_vals = [math.exp((s - n_max) / T) for s in normalized]
        total = sum(exp_vals)
        weights = [e / total for e in exp_vals]

        # Weighted random selection
        roll = self.rng.random()
        cumulative = 0.0
        for i, w in enumerate(weights):
            cumulative += w
            if roll < cumulative:
                return candidates[i]
        return candidates[-1]

    def _pick_esv_target(
        self,
        attacker: Alliance,
        available: list[Alliance],
        state: GameState,
    ) -> Alliance:
        scores = {
            d.alliance_id: self._calculate_esv(attacker, d, state)
            for d in available
        }

        if self.targeting_temperature > 0:
            return self._softmax_select(available, scores)

        # Deterministic: sort by ESV desc, spice desc, id asc
        available_sorted = sorted(
            available,
            key=lambda d: (
                -scores[d.alliance_id],
                -state.current_spice[d.alliance_id],
                d.alliance_id,
            ),
        )
        return available_sorted[0]

    def _pick_highest_spice_target(
        self,
        available: list[Alliance],
        state: GameState,
    ) -> Alliance:
        if self.targeting_temperature > 0:
            scores = {
                d.alliance_id: float(state.current_spice[d.alliance_id])
                for d in available
            }
            return self._softmax_select(available, scores)

        return max(
            available,
            key=lambda d: state.current_spice[d.alliance_id],
        )

    def _pick_by_strategy(
        self,
        attacker: Alliance,
        available: list[Alliance],
        state: GameState,
        strategy: str,
    ) -> Alliance:
        if strategy == "expected_value":
            return self._pick_esv_target(attacker, available, state)
        elif strategy == "highest_spice":
            return self._pick_highest_spice_target(available, state)
        elif strategy == "rank_aware":
            return self._pick_rank_aware_target(attacker, available, state)
        else:
            return self._pick_esv_target(attacker, available, state)

    @staticmethod
    def _rank_and_tier(
        alliance_id: str, spice_dict: dict[str, int]
    ) -> tuple[int, int]:
        sorted_ids = sorted(
            spice_dict.keys(),
            key=lambda aid: (-spice_dict[aid], aid),
        )
        rank = sorted_ids.index(alliance_id) + 1
        if rank == 1:
            tier = 1
        elif rank <= 3:
            tier = 2
        elif rank <= 10:
            tier = 3
        elif rank <= 20:
            tier = 4
        else:
            tier = 5
        return rank, tier

    def _pick_rank_aware_target(
        self,
        attacker: Alliance,
        available: list[Alliance],
        state: GameState,
    ) -> Alliance:
        cur_rank, cur_tier = self._rank_and_tier(
            attacker.alliance_id, state.current_spice
        )

        scores: dict[str, int] = {}
        esvs: dict[str, float] = {}

        for d in available:
            esv = self._calculate_esv(attacker, d, state)
            esvs[d.alliance_id] = esv
            transfer = round(esv)

            projected = dict(state.current_spice)
            projected[attacker.alliance_id] += transfer
            projected[d.alliance_id] -= transfer

            proj_rank, proj_tier = self._rank_and_tier(
                attacker.alliance_id, projected
            )

            tier_improvement = cur_tier - proj_tier
            rank_improvement = cur_rank - proj_rank
            scores[d.alliance_id] = tier_improvement * 1000 + rank_improvement

        if self.targeting_temperature > 0:
            return self._softmax_select(available, scores)

        return sorted(
            available,
            key=lambda d: (
                -scores[d.alliance_id],
                -esvs[d.alliance_id],
                -state.current_spice[d.alliance_id],
                d.alliance_id,
            ),
        )[0]

    def _get_top_n_ids(
        self,
        state: GameState,
        attacking_faction: str,
    ) -> set[str]:
        n = self.config.get("tier_optimization_top_n", 5)
        faction_alliances = [
            a for a in state.alliances if a.faction == attacking_faction
        ]
        sorted_by_spice = sorted(
            faction_alliances,
            key=lambda a: (-state.current_spice[a.alliance_id], a.alliance_id),
        )
        return {a.alliance_id for a in sorted_by_spice[:n]}

    def _forward_sim_tier(
        self,
        attacker_id: str,
        defender_id: str,
        state: GameState,
    ) -> tuple[int, int]:
        from spice_war.game.simulator import simulate_war

        synthetic = [
            Alliance(
                alliance_id=a.alliance_id,
                faction=a.faction,
                power=a.power,
                starting_spice=state.current_spice[a.alliance_id],
                daily_spice_rate=a.daily_spice_rate,
                name=a.name,
                server=a.server,
            )
            for a in state.alliances
        ]

        current_ec = state.event_schedule[state.event_number - 1]
        forward_schedule = [
            EventConfig(
                attacker_faction=current_ec.attacker_faction,
                day=current_ec.day,
                days_before=0,
            )
        ] + list(state.event_schedule[state.event_number:])

        forward_config = {
            "random_seed": 0,
            "targeting_strategy": "rank_aware",
            "targeting_temperature": 0,
            "power_noise": 0,
            "outcome_noise": 0,
            "battle_outcome_matrix": self.config.get("battle_outcome_matrix", {}),
            "damage_weights": self.config.get("damage_weights", {}),
            "event_targets": {"1": {attacker_id: defender_id}},
        }

        forward_model = ConfigurableModel(forward_config, synthetic)
        result = simulate_war(synthetic, forward_schedule, forward_model)

        tier = result["rankings"][attacker_id]
        rank = self._rank_and_tier(attacker_id, result["final_spice"])[0]
        return tier, rank

    def _pick_maximize_tier_target(
        self,
        attacker: Alliance,
        available: list[Alliance],
        state: GameState,
    ) -> Alliance:
        candidates = []
        for d in available:
            tier, rank = self._forward_sim_tier(
                attacker.alliance_id, d.alliance_id, state
            )
            esv = self._calculate_esv(attacker, d, state)
            candidates.append((d, tier, rank, esv))

        candidates.sort(
            key=lambda x: (x[1], x[2], -x[3], x[0].alliance_id)
        )
        return candidates[0][0]

    # ── M2: Reinforcements ─────────────────────────────────────────

    def generate_reinforcements(
        self,
        state: GameState,
        targets: dict[str, str],
        bracket_defenders: list[Alliance],
        bracket_number: int,
    ) -> dict[str, str]:
        event_reinforcements = self.config.get("event_reinforcements", {})
        event_key = str(state.event_number)

        if event_key in event_reinforcements:
            configured = event_reinforcements[event_key]
            defender_ids = {d.alliance_id for d in bracket_defenders}
            filtered = {k: v for k, v in configured.items() if k in defender_ids}
            if filtered:
                return filtered

        return self._default_reinforcements(targets, bracket_defenders, state)

    def _default_reinforcements(
        self,
        targets: dict[str, str],
        bracket_defenders: list[Alliance],
        state: GameState,
    ) -> dict[str, str]:
        targeted_set = set(targets.values())
        untargeted = [
            d for d in bracket_defenders if d.alliance_id not in targeted_set
        ]

        if not untargeted:
            return {}

        target_counts = Counter(targets.values())
        if not target_counts:
            return {}

        # Sort candidates by (attacker_count desc, spice desc) for tie-breaking
        candidates = sorted(
            target_counts.keys(),
            key=lambda did: (
                target_counts[did],
                state.current_spice.get(did, 0),
            ),
            reverse=True,
        )
        most_attacked = candidates[0]
        max_reinforcements = target_counts[most_attacked] - 1

        reinforcements: dict[str, str] = {}
        for d in untargeted[:max_reinforcements]:
            reinforcements[d.alliance_id] = most_attacked

        return reinforcements

    # ── M3: Battle Outcome ─────────────────────────────────────────

    def determine_battle_outcome(
        self,
        state: GameState,
        attackers: list[Alliance],
        defenders: list[Alliance],
        day: str,
    ) -> tuple[str, dict[str, float]]:
        primary_defender = defenders[0]
        matrix = self.config.get("battle_outcome_matrix", {})

        probs_list = []
        for attacker in attackers:
            probs = self._lookup_or_heuristic(
                matrix, attacker, primary_defender, day
            )
            if self.outcome_noise > 0:
                probs = self._apply_outcome_noise(
                    probs, attacker.alliance_id, primary_defender.alliance_id
                )
            probs_list.append(probs)

        if len(probs_list) == 1:
            combined = probs_list[0]
        else:
            combined = {
                "full_success": sum(p["full_success"] for p in probs_list)
                / len(probs_list),
                "partial_success": sum(p["partial_success"] for p in probs_list)
                / len(probs_list),
            }

            # Average custom probability across all attackers (0 for those without)
            custom_probs = [p.get("custom", 0.0) for p in probs_list]
            custom_avg = sum(custom_probs) / len(probs_list)

            if custom_avg > 0:
                combined["custom"] = custom_avg
                # Average theft % only across attackers that have it
                theft_pcts = [
                    p["custom_theft_percentage"]
                    for p in probs_list
                    if "custom_theft_percentage" in p
                ]
                combined["custom_theft_percentage"] = (
                    sum(theft_pcts) / len(theft_pcts)
                )

            # Clamp and renormalize the averaged result
            combined["full_success"] = max(0.0, combined["full_success"])
            combined["partial_success"] = max(0.0, combined["partial_success"])
            if "custom" in combined:
                combined["custom"] = max(0.0, combined["custom"])
            non_fail = (
                combined["full_success"]
                + combined["partial_success"]
                + combined.get("custom", 0.0)
            )
            if non_fail > 1.0:
                combined["full_success"] /= non_fail
                combined["partial_success"] /= non_fail
                if "custom" in combined:
                    combined["custom"] /= non_fail

        combined["fail"] = max(
            0.0,
            1.0
            - combined["full_success"]
            - combined["partial_success"]
            - combined.get("custom", 0.0),
        )

        # Outcome roll
        roll = self.rng.random()
        cumulative = combined["full_success"]
        if roll < cumulative:
            outcome = "full_success"
        else:
            cumulative += combined["partial_success"]
            if roll < cumulative:
                outcome = "partial_success"
            elif "custom" in combined:
                cumulative += combined["custom"]
                if roll < cumulative:
                    outcome = "custom"
                else:
                    outcome = "fail"
            else:
                outcome = "fail"

        return outcome, combined

    def _lookup_or_heuristic(
        self,
        matrix: dict,
        attacker: Alliance,
        defender: Alliance,
        day: str,
    ) -> dict[str, float]:
        day_matrix = matrix.get(day, {})

        # 1. Exact pairing
        attacker_entry = day_matrix.get(attacker.alliance_id, {})
        pairing = attacker_entry.get(defender.alliance_id)
        if pairing is not None:
            return self._parse_pairing(pairing)

        # 2. Attacker default (A → "*")
        wildcard_pairing = attacker_entry.get("*")
        if wildcard_pairing is not None:
            return self._parse_pairing(wildcard_pairing)

        # 3. Defender default ("*" → D)
        wildcard_attacker = day_matrix.get("*", {})
        defender_pairing = wildcard_attacker.get(defender.alliance_id)
        if defender_pairing is not None:
            return self._parse_pairing(defender_pairing)

        # 4. Heuristic fallback
        return self._heuristic_probabilities(attacker, defender, day)

    def _parse_pairing(self, pairing: dict) -> dict[str, float]:
        full = pairing.get("full_success", 0.0)
        result = {"full_success": full}

        if "partial_success" in pairing:
            result["partial_success"] = pairing["partial_success"]
        elif "custom" not in pairing:
            result["partial_success"] = (1.0 - full) * 0.4
        else:
            result["partial_success"] = 0.0

        if "custom" in pairing:
            result["custom"] = pairing["custom"]
            result["custom_theft_percentage"] = pairing["custom_theft_percentage"]

        return result

    def _heuristic_probabilities(
        self, attacker: Alliance, defender: Alliance, day: str
    ) -> dict[str, float]:
        ratio = self._get_power(attacker.alliance_id) / self._get_power(defender.alliance_id)
        return heuristic_from_ratio(ratio, day)

    def _apply_outcome_noise(
        self,
        probs: dict[str, float],
        attacker_id: str,
        defender_id: str,
    ) -> dict[str, float]:
        offsets = self._pairing_offsets.get((attacker_id, defender_id))
        if offsets is None:
            return probs

        result = dict(probs)

        result["full_success"] = max(0.0, result["full_success"] + offsets["full_success"])
        result["partial_success"] = max(0.0, result["partial_success"] + offsets["partial_success"])

        if "custom" in result:
            result["custom"] = max(0.0, result["custom"] + offsets["custom"])

        # Renormalize if non-fail probabilities exceed 1
        non_fail = result["full_success"] + result["partial_success"] + result.get("custom", 0.0)
        if non_fail > 1.0:
            result["full_success"] /= non_fail
            result["partial_success"] /= non_fail
            if "custom" in result:
                result["custom"] /= non_fail

        return result

    # ── M4: Damage Splits ──────────────────────────────────────────

    def determine_damage_splits(
        self,
        state: GameState,
        attackers: list[Alliance],
        primary_defender: Alliance,
    ) -> dict[str, float]:
        if len(attackers) == 1:
            return {attackers[0].alliance_id: 1.0}

        damage_weights_config = self.config.get("damage_weights", {})
        all_have_weights = all(
            a.alliance_id in damage_weights_config for a in attackers
        )

        if all_have_weights:
            weights = {
                a.alliance_id: damage_weights_config[a.alliance_id]
                for a in attackers
            }
        else:
            weights = {}
            for a in attackers:
                ratio = self._get_power(a.alliance_id) / self._get_power(primary_defender.alliance_id)
                weights[a.alliance_id] = max(0.0, min(1.0, 1.5 * ratio - 1.0))

        total = sum(weights.values())
        if total == 0:
            equal = 1.0 / len(attackers)
            return {a.alliance_id: equal for a in attackers}

        return {aid: w / total for aid, w in weights.items()}
