from __future__ import annotations

import csv
import io
import json
import textwrap
from unittest.mock import patch

import pytest

from spice_war.sheets.importer import fetch_csv_rows, import_from_csv
from spice_war.sheets.template import generate_template
from spice_war.utils.data_structures import Alliance, EventConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def alliances():
    """Two-faction setup with 3 alliances each, varied power."""
    return [
        Alliance("A1", "red", 300, 1000, 100),
        Alliance("A2", "red", 200, 800, 80),
        Alliance("A3", "red", 100, 600, 60),
        Alliance("B1", "blue", 250, 900, 90),
        Alliance("B2", "blue", 150, 700, 70),
        Alliance("B3", "blue", 50, 500, 50),
    ]


@pytest.fixture
def schedule():
    return [
        EventConfig("red", "wednesday", 3),
        EventConfig("blue", "saturday", 4),
    ]


# ---------------------------------------------------------------------------
# Template tests
# ---------------------------------------------------------------------------

class TestGenerateTemplate:
    def test_sections_present(self, alliances, schedule):
        rows = generate_template(alliances, schedule)
        flat = "\n".join(",".join(r) for r in rows)
        assert "random_seed" in flat
        assert "targeting_strategy" in flat
        assert "default_targets" in flat
        assert "event_targets" in flat
        assert "battle_outcome_matrix" in flat

    def test_alliances_sorted_by_power(self, alliances, schedule):
        rows = generate_template(alliances, schedule, top_n=3)
        # Find the default_targets data rows (after the header row)
        in_default = False
        target_alliances = []
        for row in rows:
            if row and row[0] == "alliance":
                in_default = True
                continue
            if in_default:
                if not row or not row[0] or row[0].startswith(("default_", "event_", "battle_")):
                    break
                target_alliances.append(row[0])
        # Red sorted: A1(300), A2(200), A3(100); Blue: B1(250), B2(150), B3(50)
        assert target_alliances == ["A1", "A2", "A3", "B1", "B2", "B3"]

    def test_top_n_respected(self, alliances, schedule):
        rows = generate_template(alliances, schedule, top_n=2)
        in_default = False
        target_alliances = []
        for row in rows:
            if row and row[0] == "alliance":
                in_default = True
                continue
            if in_default:
                if not row or not row[0] or row[0].startswith(("default_", "event_", "battle_")):
                    break
                target_alliances.append(row[0])
        # Only top 2 per faction
        assert target_alliances == ["A1", "A2", "B1", "B2"]

    def test_descriptions_included(self, alliances, schedule):
        rows = generate_template(alliances, schedule)
        flat = "\n".join(",".join(r) for r in rows)
        assert "Override the default targeting" in flat
        assert "Override targeting for a specific event" in flat
        assert "Full-success probabilities" in flat

    def test_event_targets_has_correct_attackers(self, alliances, schedule):
        rows = generate_template(alliances, schedule, top_n=2)
        # Find event_targets data
        in_events = False
        event_rows = []
        for row in rows:
            if row and row[0] == "event":
                in_events = True
                continue
            if in_events:
                if not row or not row[0] or row[0].startswith(("default_", "event_t", "battle_")):
                    break
                event_rows.append(row)
        # Event 1: red attacks -> A1, A2; Event 2: blue attacks -> B1, B2
        assert len(event_rows) == 4
        assert event_rows[0][0:2] == ["1", "A1"]
        assert event_rows[1][0:2] == ["1", "A2"]
        assert event_rows[2][0:2] == ["2", "B1"]
        assert event_rows[3][0:2] == ["2", "B2"]

    def test_probability_grid_structure(self, alliances, schedule):
        rows = generate_template(alliances, schedule, top_n=2)

        # 4 grids should be present (sorted factions: blue, red)
        titles = [r[0] for r in rows if r and "\u2192" in r[0]]
        assert len(titles) == 4
        assert "Wednesday: blue \u2192 red" in titles
        assert "Wednesday: red \u2192 blue" in titles
        assert "Saturday: blue \u2192 red" in titles
        assert "Saturday: red \u2192 blue" in titles

        # Check a specific grid: "Wednesday: red → blue"
        grid_start = None
        for idx, row in enumerate(rows):
            if row and row[0] == "Wednesday: red \u2192 blue":
                grid_start = idx
                break
        assert grid_start is not None

        # Header row: blank + defender IDs (blue faction, sorted by power)
        header = rows[grid_start + 1]
        assert header[0] == ""
        assert header[1] == "B1"
        assert header[2] == "B2"

        # Data rows with heuristic values
        # A1(300) vs B1(250): r=1.2, wed: 2.5*1.2-2.0=1.0 → 100%
        # A1(300) vs B2(150): r=2.0, wed: 2.5*2.0-2.0=3.0 → 100%
        data1 = rows[grid_start + 2]
        assert data1[0] == "A1"
        assert data1[1] == "100"
        assert data1[2] == "100"

        # A2(200) vs B1(250): r=0.8, wed: 2.5*0.8-2.0=0.0 → 0%
        # A2(200) vs B2(150): r=1.333, wed: 2.5*1.333-2.0=1.333 → 100%
        data2 = rows[grid_start + 3]
        assert data2[0] == "A2"
        assert data2[1] == "0"
        assert data2[2] == "100"


# ---------------------------------------------------------------------------
# Importer tests
# ---------------------------------------------------------------------------

class TestImportFromCsv:
    def test_scalar_parsing(self):
        rows = [
            ["Spice War Model Configuration Template"],
            ["Some description text"],
            [],
            ["random_seed", "42"],
            ["targeting_strategy", "expected_value"],
        ]
        result = import_from_csv(rows)
        assert result["random_seed"] == 42
        assert result["targeting_strategy"] == "expected_value"

    def test_default_targets_parsing(self):
        rows = [
            ["random_seed", "1"],
            [],
            ["default_targets: Override targeting..."],
            ["alliance", "type", "value"],
            ["A1", "target", "B1"],
            ["A2", "strategy", "highest_spice"],
            ["A3", "", ""],  # blank type → skip
            [],
        ]
        result = import_from_csv(rows)
        assert result["default_targets"] == {
            "A1": {"target": "B1"},
            "A2": {"strategy": "highest_spice"},
        }

    def test_event_targets_parsing(self):
        rows = [
            ["event_targets: Override targeting..."],
            ["event", "alliance", "type", "value"],
            ["1", "A1", "target", "B1"],
            ["2", "B1", "strategy", "expected_value"],
            ["2", "B2", "", ""],  # blank type → skip
            [],
        ]
        result = import_from_csv(rows)
        assert result["event_targets"] == {
            "1": {"A1": {"target": "B1"}},
            "2": {"B1": {"strategy": "expected_value"}},
        }

    def test_probability_grid_parsing(self):
        rows = [
            ["Wednesday: red \u2192 blue"],
            ["", "B1", "B2"],
            ["A1", "80", "90"],
            ["A2", "50", ""],
            [],
        ]
        result = import_from_csv(rows)
        matrix = result["battle_outcome_matrix"]
        assert matrix["wednesday"]["A1"]["B1"] == {"full_success": 0.8}
        assert matrix["wednesday"]["A1"]["B2"] == {"full_success": 0.9}
        assert matrix["wednesday"]["A2"]["B1"] == {"full_success": 0.5}
        assert "B2" not in matrix["wednesday"]["A2"]

    def test_percentage_to_decimal_conversion(self):
        rows = [
            ["Saturday: alpha \u2192 beta"],
            ["", "D1"],
            ["A1", "45"],
            ["A2", "0"],
            ["A3", "100"],
            [],
        ]
        result = import_from_csv(rows)
        matrix = result["battle_outcome_matrix"]
        assert matrix["saturday"]["A1"]["D1"]["full_success"] == 0.45
        assert matrix["saturday"]["A2"]["D1"]["full_success"] == 0.0
        assert matrix["saturday"]["A3"]["D1"]["full_success"] == 1.0

    def test_blank_row_skipping(self):
        rows = [
            [],
            [],
            ["random_seed", "99"],
            [],
            [],
        ]
        result = import_from_csv(rows)
        assert result["random_seed"] == 99

    def test_description_row_skipping(self):
        rows = [
            ["Spice War Model Configuration Template"],
            ["Fill in the blank cells below..."],
            [],
            ["random_seed", "7"],
        ]
        result = import_from_csv(rows)
        assert result["random_seed"] == 7

    def test_empty_input(self):
        assert import_from_csv([]) == {}


class TestFetchCsvRows:
    def test_google_url_extraction(self):
        url = "https://docs.google.com/spreadsheets/d/1aBcDeFgHiJkLmNoPqRsTuVwXyZ/edit#gid=0"
        csv_content = "a,b\n1,2\n"

        with patch("spice_war.sheets.importer.urllib.request.urlopen") as mock_urlopen:
            mock_resp = mock_urlopen.return_value.__enter__.return_value
            mock_resp.read.return_value = csv_content.encode("utf-8")
            rows = fetch_csv_rows(url)

        call_url = mock_urlopen.call_args[0][0]
        assert "1aBcDeFgHiJkLmNoPqRsTuVwXyZ" in call_url
        assert "export?format=csv" in call_url
        assert rows == [["a", "b"], ["1", "2"]]

    def test_local_file(self, tmp_path):
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("x,y\n3,4\n")
        rows = fetch_csv_rows(str(csv_file))
        assert rows == [["x", "y"], ["3", "4"]]


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_generate_then_import(self, alliances, schedule):
        """Generate template, fill in values, import, verify structure."""
        rows = generate_template(alliances, schedule, top_n=2)

        # Fill in some values
        for row in rows:
            # Fill a default_target
            if len(row) >= 3 and row[0] == "A1" and row[1] == "":
                row[1] = "target"
                row[2] = "B1"
            # Fill an event_target
            if len(row) >= 4 and row[0] == "1" and row[1] == "A1" and row[2] == "":
                row[2] = "target"
                row[3] = "B2"

        model = import_from_csv(rows)

        assert model["random_seed"] == 42
        assert model["targeting_strategy"] == "expected_value"
        assert model["default_targets"]["A1"] == {"target": "B1"}
        assert model["event_targets"]["1"]["A1"] == {"target": "B2"}
        # Grids with heuristic values should be parsed
        assert "battle_outcome_matrix" in model
        # Check a specific heuristic value from "Wednesday: red → blue" grid
        # A1(300) vs B1(250): r=1.2, wed: 1.0 → 100% → 1.0
        assert model["battle_outcome_matrix"]["wednesday"]["A1"]["B1"]["full_success"] == 1.0

    def test_csv_serialization_round_trip(self, alliances, schedule):
        """Generate → write CSV → read CSV → import."""
        rows = generate_template(alliances, schedule, top_n=2)

        # Fill in a scalar override
        for row in rows:
            if row and row[0] == "random_seed":
                row[1] = "99"

        # Write to CSV string and read back
        buf = io.StringIO()
        csv.writer(buf).writerows(rows)
        buf.seek(0)
        parsed_rows = list(csv.reader(buf))

        model = import_from_csv(parsed_rows)
        assert model["random_seed"] == 99
        # Verify grid data survives serialization
        assert "battle_outcome_matrix" in model
        assert "wednesday" in model["battle_outcome_matrix"]


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestGenerateTemplateCli:
    def test_basic_run(self, tmp_path):
        from scripts.generate_sheet_template import main

        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "alliances": [
                {"alliance_id": "X1", "faction": "a", "power": 100, "starting_spice": 1000, "daily_rate": 50},
                {"alliance_id": "Y1", "faction": "b", "power": 90, "starting_spice": 900, "daily_rate": 45},
            ],
            "event_schedule": [
                {"attacker_faction": "a", "day": "wednesday", "days_before": 3},
                {"attacker_faction": "b", "day": "saturday", "days_before": 4},
            ],
        }))
        output_file = tmp_path / "template.csv"
        ret = main([str(state_file), "--output", str(output_file)])
        assert ret == 0
        assert output_file.exists()
        content = output_file.read_text()
        assert "X1" in content
        assert "Y1" in content

    def test_invalid_state(self, tmp_path):
        from scripts.generate_sheet_template import main

        state_file = tmp_path / "bad.json"
        state_file.write_text("{}")
        ret = main([str(state_file)])
        assert ret == 1


class TestImportSheetCli:
    def test_basic_import(self, tmp_path):
        from scripts.import_sheet import main

        csv_file = tmp_path / "input.csv"
        csv_file.write_text(
            "random_seed,42\n"
            "targeting_strategy,expected_value\n"
        )
        output_file = tmp_path / "model.json"
        ret = main([str(csv_file), "--output", str(output_file)])
        assert ret == 0
        model = json.loads(output_file.read_text())
        assert model["random_seed"] == 42

    def test_with_state_validation(self, tmp_path):
        from scripts.import_sheet import main

        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "alliances": [
                {"alliance_id": "X1", "faction": "a", "power": 100, "starting_spice": 1000, "daily_rate": 50},
                {"alliance_id": "Y1", "faction": "b", "power": 90, "starting_spice": 900, "daily_rate": 45},
            ],
            "event_schedule": [
                {"attacker_faction": "a", "day": "wednesday", "days_before": 3},
                {"attacker_faction": "b", "day": "saturday", "days_before": 4},
            ],
        }))

        # CSV with a reference to unknown alliance
        csv_file = tmp_path / "input.csv"
        csv_file.write_text(
            "default_targets: Override\n"
            "alliance,type,value\n"
            "UNKNOWN,target,Y1\n"
        )
        output_file = tmp_path / "model.json"
        ret = main([str(csv_file), "--output", str(output_file), "--state-file", str(state_file)])
        assert ret == 1  # Validation should fail

    def test_missing_input(self, tmp_path):
        from scripts.import_sheet import main

        output_file = tmp_path / "model.json"
        ret = main([str(tmp_path / "nonexistent.csv"), "--output", str(output_file)])
        assert ret == 1
