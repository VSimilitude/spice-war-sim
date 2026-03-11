import pytest

from spice_war.models.configurable import ConfigurableModel, heuristic_from_ratio
from spice_war.utils.data_structures import Alliance
from spice_war.web.bridge import (
    compute_heuristic,
    generate_template_csv,
    get_default_model_config,
    get_default_state,
    import_csv,
    run_monte_carlo,
    run_single,
    validate_model_config,
    validate_state,
)


@pytest.fixture
def default_state():
    return get_default_state()


@pytest.fixture
def valid_state():
    """Minimal 2-alliance, 1-event state for fast tests."""
    return {
        "alliances": [
            {
                "alliance_id": "A1",
                "faction": "red",
                "power": 10.0,
                "starting_spice": 1_000_000,
                "daily_rate": 30_000,
            },
            {
                "alliance_id": "D1",
                "faction": "blue",
                "power": 10.0,
                "starting_spice": 1_000_000,
                "daily_rate": 30_000,
            },
        ],
        "event_schedule": [
            {"attacker_faction": "red", "day": "wednesday", "days_before": 7},
        ],
    }


# --- get_default_state ---


def test_get_default_state_is_valid(default_state):
    result = validate_state(default_state)
    assert result["ok"] is True
    assert len(result["alliances"]) == 46
    assert len(result["event_schedule"]) == 1


# --- get_default_model_config ---


def test_get_default_model_config_is_valid(default_state):
    model = get_default_model_config()
    result = validate_model_config(model, default_state)
    assert result["ok"] is True


# --- validate_state ---


def test_validate_state_accepts_good_input(valid_state):
    result = validate_state(valid_state)
    assert result["ok"] is True
    assert len(result["alliances"]) == 2
    assert result["alliances"][0]["alliance_id"] == "A1"


def test_validate_state_rejects_missing_alliances():
    result = validate_state({"event_schedule": []})
    assert result["ok"] is False
    assert "alliances" in result["error"]


def test_validate_state_rejects_missing_alliance_fields():
    state = {
        "alliances": [
            {"alliance_id": "A1", "faction": "red", "starting_spice": 100, "daily_rate": 10},
            {"alliance_id": "D1", "faction": "blue", "power": 10.0, "starting_spice": 100, "daily_rate": 10},
        ],
        "event_schedule": [
            {"attacker_faction": "red", "day": "wednesday", "days_before": 7},
        ],
    }
    result = validate_state(state)
    assert result["ok"] is False
    assert "missing" in result["error"].lower()


def test_validate_state_rejects_single_faction():
    state = {
        "alliances": [
            {"alliance_id": "A1", "faction": "red", "power": 10.0, "starting_spice": 100, "daily_rate": 10},
            {"alliance_id": "A2", "faction": "red", "power": 10.0, "starting_spice": 100, "daily_rate": 10},
        ],
        "event_schedule": [
            {"attacker_faction": "red", "day": "wednesday", "days_before": 7},
        ],
    }
    result = validate_state(state)
    assert result["ok"] is False
    assert "2 factions" in result["error"]


def test_validate_state_rejects_duplicate_ids():
    state = {
        "alliances": [
            {"alliance_id": "A1", "faction": "red", "power": 10.0, "starting_spice": 100, "daily_rate": 10},
            {"alliance_id": "A1", "faction": "blue", "power": 10.0, "starting_spice": 100, "daily_rate": 10},
        ],
        "event_schedule": [
            {"attacker_faction": "red", "day": "wednesday", "days_before": 7},
        ],
    }
    result = validate_state(state)
    assert result["ok"] is False
    assert "Duplicate" in result["error"]


# --- validate_model_config ---


def test_validate_model_config_accepts_empty(valid_state):
    result = validate_model_config({}, valid_state)
    assert result["ok"] is True


def test_validate_model_config_rejects_unknown_keys(valid_state):
    result = validate_model_config({"unknown_key": 1}, valid_state)
    assert result["ok"] is False
    assert "unknown" in result["error"].lower()


def test_validate_model_config_rejects_bad_alliance_ref(valid_state):
    model = {
        "event_targets": {
            "1": {"NONEXISTENT": {"target": "D1"}},
        },
    }
    result = validate_model_config(model, valid_state)
    assert result["ok"] is False


# --- run_single ---


def test_run_single_structure(default_state):
    result = run_single(default_state, {})
    assert result["ok"] is True
    assert "seed" in result
    assert "final_spice" in result
    assert "rankings" in result
    assert "event_history" in result
    assert len(result["event_history"]) == 1
    for aid in ["VON", "UTW", "Ghst", "SPXP"]:
        assert aid in result["final_spice"]
        assert aid in result["rankings"]


def test_run_single_deterministic(default_state):
    r1 = run_single(default_state, {}, seed=42)
    r2 = run_single(default_state, {}, seed=42)
    assert r1["ok"] is True
    assert r2["ok"] is True
    assert r1["final_spice"] == r2["final_spice"]
    assert r1["rankings"] == r2["rankings"]


def test_run_single_reports_validation_errors():
    result = run_single({"event_schedule": []}, {})
    assert result["ok"] is False


# --- run_monte_carlo ---


def test_run_monte_carlo_structure(default_state):
    result = run_monte_carlo(default_state, {}, num_iterations=10)
    assert result["ok"] is True
    assert result["num_iterations"] == 10
    assert "base_seed" in result
    assert "tier_distribution" in result
    assert "spice_stats" in result
    assert "raw_results" in result


def test_run_monte_carlo_iteration_count(default_state):
    result = run_monte_carlo(default_state, {}, num_iterations=25)
    assert result["ok"] is True
    assert len(result["raw_results"]) == 25


def test_run_monte_carlo_tier_sums(default_state):
    result = run_monte_carlo(default_state, {}, num_iterations=100)
    assert result["ok"] is True
    for aid in ["VON", "UTW", "Ghst", "SPXP"]:
        dist = result["tier_distribution"][aid]
        total = sum(float(dist[str(t)]) for t in range(1, 6))
        assert total == pytest.approx(1.0)


def test_run_monte_carlo_spice_stats_structure(default_state):
    result = run_monte_carlo(default_state, {}, num_iterations=50)
    assert result["ok"] is True
    for aid in ["VON", "UTW", "Ghst", "SPXP"]:
        stats = result["spice_stats"][aid]
        assert set(stats.keys()) == {"mean", "median", "min", "max", "p25", "p75"}
        assert stats["min"] <= stats["p25"] <= stats["median"] <= stats["p75"] <= stats["max"]


# --- import_csv ---


def test_import_csv_round_trip(default_state):
    template_result = generate_template_csv(default_state)
    assert template_result["ok"] is True

    import_result = import_csv(template_result["csv"])
    assert import_result["ok"] is True
    assert "random_seed" in import_result["config"]


def test_import_csv_unrecognized_rows():
    result = import_csv("not,valid,csv,data\nwith,random,stuff,here")
    assert result["ok"] is True
    assert result["config"] == {}


# --- Heuristic consistency ---

@pytest.mark.parametrize("day", ["wednesday", "saturday"])
@pytest.mark.parametrize("ratio", [0.3, 0.5, 0.6, 0.8, 1.0, 1.2, 1.5, 2.0])
def test_compute_heuristic_matches_model(day, ratio):
    """Bridge heuristic must match the model's internal heuristic."""
    att_power = 1_000_000 * ratio
    def_power = 1_000_000

    # Bridge function (what the web UI calls)
    bridge_result = compute_heuristic(att_power, def_power, day)

    # Model's internal heuristic (what the engine uses)
    model_result = heuristic_from_ratio(ratio, day)

    assert bridge_result["full"] == round(model_result["full_success"] * 100)
    assert bridge_result["partial"] == round(model_result["partial_success"] * 100)


@pytest.mark.parametrize("day", ["wednesday", "saturday"])
def test_model_heuristic_uses_shared_function(day):
    """ConfigurableModel._heuristic_probabilities must delegate to heuristic_from_ratio."""
    att = Alliance("A", "red", 1_500_000, 0, 0)
    defn = Alliance("B", "blue", 1_000_000, 0, 0)

    model = ConfigurableModel({"random_seed": 0}, [att, defn])
    model.set_effective_powers()

    model_probs = model._heuristic_probabilities(att, defn, day)
    direct_probs = heuristic_from_ratio(1.5, day)

    assert model_probs == direct_probs
