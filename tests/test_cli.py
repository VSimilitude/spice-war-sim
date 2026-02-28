import json
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
STATE_FILE = FIXTURES / "sample_state.json"
MODEL_FILE = FIXTURES / "sample_model.json"
RUN_BATTLE = Path(__file__).parent.parent / "scripts" / "run_battle.py"


def _run(args, check=True):
    result = subprocess.run(
        [sys.executable, str(RUN_BATTLE)] + args,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"CLI failed:\nstdout: {result.stdout}\nstderr: {result.stderr}")
    return result


class TestCLI:
    def test_stdout_format(self):
        result = _run([str(STATE_FILE), str(MODEL_FILE), "--seed", "42"])
        output = result.stdout
        assert "State:" in output
        assert "Model:" in output
        assert "Seed:  42" in output
        assert "Initial State:" in output
        assert "RedWolves" in output
        assert "Event 1:" in output
        assert "Final Results:" in output
        assert "tier=" in output

    def test_json_output(self, tmp_path):
        output_path = tmp_path / "replay.json"
        _run([str(STATE_FILE), str(MODEL_FILE), "--seed", "42", "--output", str(output_path)])
        assert output_path.exists()
        with open(output_path) as f:
            replay = json.load(f)
        assert replay["seed"] == 42
        assert "initial_state" in replay
        assert "events" in replay
        assert len(replay["events"]) == 2
        assert "final_spice" in replay
        assert "rankings" in replay
        # Check event structure
        event = replay["events"][0]
        assert "spice_before" in event
        assert "spice_after" in event
        assert "battles" in event
        battle = event["battles"][0]
        assert "outcome" in battle
        assert "outcome_probabilities" in battle
        assert "defender_buildings" in battle
        assert "theft_percentage" in battle
        assert "transfers" in battle

    def test_quiet_suppresses_stdout(self, tmp_path):
        output_path = tmp_path / "replay.json"
        result = _run([
            str(STATE_FILE), str(MODEL_FILE),
            "--seed", "42", "--quiet", "--output", str(output_path),
        ])
        assert result.stdout == ""

    def test_reproducibility(self):
        result1 = _run([str(STATE_FILE), str(MODEL_FILE), "--seed", "42"])
        result2 = _run([str(STATE_FILE), str(MODEL_FILE), "--seed", "42"])
        assert result1.stdout == result2.stdout

    def test_heuristic_only(self):
        """Run without model file — all heuristics."""
        result = _run([str(STATE_FILE), "--seed", "99"])
        assert "Model: (none, using heuristics)" in result.stdout
        assert "Final Results:" in result.stdout

    def test_validation_error(self, tmp_path):
        bad_state = tmp_path / "bad.json"
        bad_state.write_text('{"alliances": []}')
        result = _run([str(bad_state)], check=False)
        assert result.returncode == 1
        assert "Error:" in result.stderr
