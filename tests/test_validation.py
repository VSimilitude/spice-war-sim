import json
import tempfile
from pathlib import Path

import pytest

from spice_war.utils.validation import ValidationError, load_model_config, load_state


def _write_json(tmp_path, name, data):
    p = tmp_path / name
    p.write_text(json.dumps(data))
    return str(p)


def _valid_state():
    return {
        "alliances": [
            {"alliance_id": "a1", "faction": "red", "power": 100, "starting_spice": 500000, "daily_rate": 50000},
            {"alliance_id": "a2", "faction": "blue", "power": 80, "starting_spice": 400000, "daily_rate": 40000},
        ],
        "event_schedule": [
            {"attacker_faction": "red", "day": "wednesday", "days_before": 3},
        ],
    }


class TestLoadState:
    def test_valid(self, tmp_path):
        path = _write_json(tmp_path, "state.json", _valid_state())
        alliances, schedule = load_state(path)
        assert len(alliances) == 2
        assert len(schedule) == 1
        assert alliances[0].alliance_id == "a1"
        assert schedule[0].day == "wednesday"

    def test_missing_alliances_key(self, tmp_path):
        path = _write_json(tmp_path, "state.json", {"event_schedule": []})
        with pytest.raises(ValidationError, match="missing required key.*alliances"):
            load_state(path)

    def test_missing_alliance_field(self, tmp_path):
        data = _valid_state()
        del data["alliances"][0]["power"]
        path = _write_json(tmp_path, "state.json", data)
        with pytest.raises(ValidationError, match="missing required fields.*power"):
            load_state(path)

    def test_unknown_alliance_key(self, tmp_path):
        data = _valid_state()
        data["alliances"][0]["starting_spise"] = 100
        path = _write_json(tmp_path, "state.json", data)
        with pytest.raises(ValidationError, match="Unknown keys in alliance"):
            load_state(path)

    def test_unknown_top_level_key(self, tmp_path):
        data = _valid_state()
        data["extra_key"] = True
        path = _write_json(tmp_path, "state.json", data)
        with pytest.raises(ValidationError, match="Unknown keys in state file"):
            load_state(path)

    def test_empty_schedule(self, tmp_path):
        data = _valid_state()
        data["event_schedule"] = []
        path = _write_json(tmp_path, "state.json", data)
        with pytest.raises(ValidationError, match="must not be empty"):
            load_state(path)

    def test_missing_faction(self, tmp_path):
        data = _valid_state()
        # Remove all blue alliances
        data["alliances"] = [a for a in data["alliances"] if a["faction"] != "blue"]
        # Schedule references blue as defender implicitly (only red attacks)
        # but we need both factions
        path = _write_json(tmp_path, "state.json", data)
        with pytest.raises(ValidationError):
            load_state(path)


class TestLoadModelConfig:
    def test_none_returns_empty(self):
        assert load_model_config(None, {"a1"}) == {}

    def test_valid_model(self, tmp_path):
        data = {"random_seed": 42, "damage_weights": {"a1": 1.0}}
        path = _write_json(tmp_path, "model.json", data)
        config = load_model_config(path, {"a1"})
        assert config["random_seed"] == 42

    def test_unknown_key(self, tmp_path):
        data = {"battle_outcom_matrix": {}}
        path = _write_json(tmp_path, "model.json", data)
        with pytest.raises(ValidationError, match="Unknown keys in model file"):
            load_model_config(path, set())

    def test_cross_reference_error(self, tmp_path):
        data = {"damage_weights": {"nonexistent": 1.0}}
        path = _write_json(tmp_path, "model.json", data)
        with pytest.raises(ValidationError, match="unknown alliance.*nonexistent"):
            load_model_config(path, {"a1"})

    def test_empty_model_is_valid(self, tmp_path):
        path = _write_json(tmp_path, "model.json", {})
        config = load_model_config(path, {"a1"})
        assert config == {}
