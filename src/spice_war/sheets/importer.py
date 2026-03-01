from __future__ import annotations

import csv
import io
import re
import urllib.request
from pathlib import Path

_GOOGLE_SHEET_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]+)/")
_GRID_TITLE_RE = re.compile(r"^(\w+):\s+.+ \u2192 .+$")

_SCALAR_KEYS = {"random_seed", "targeting_strategy"}
_SECTION_HEADERS = {"default_targets", "event_targets", "battle_outcome_matrix"}


def fetch_csv_rows(url_or_path: str) -> list[list[str]]:
    """Fetch CSV rows from a Google Sheet URL or local file path."""
    match = _GOOGLE_SHEET_RE.search(url_or_path)
    if match:
        sheet_id = match.group(1)
        export_url = (
            f"https://docs.google.com/spreadsheets/d/{sheet_id}"
            f"/export?format=csv"
        )
        with urllib.request.urlopen(export_url) as resp:
            text = resp.read().decode("utf-8")
        return list(csv.reader(io.StringIO(text)))

    path = Path(url_or_path)
    with open(path, newline="") as f:
        return list(csv.reader(f))


def import_from_csv(rows: list[list[str]]) -> dict:
    """Parse CSV rows into a model config dict.

    Uses a state-machine approach: recognizes scalar keys in cell A,
    grid title rows for probability grids, section headers that start
    table parsing, and skips all other rows (descriptions, titles,
    comments, blank rows).
    """
    result: dict = {}
    i = 0

    while i < len(rows):
        row = rows[i]
        cell_a = _cell(row, 0).strip()

        # Skip blank rows and comment rows
        if not cell_a or cell_a.startswith("#"):
            i += 1
            continue

        # Check for scalar keys
        if cell_a in _SCALAR_KEYS:
            value = _cell(row, 1).strip()
            if value:
                if cell_a == "random_seed":
                    result[cell_a] = int(value)
                else:
                    result[cell_a] = value
            i += 1
            continue

        # Check for grid title (e.g. "Wednesday: blue → red")
        grid_match = _GRID_TITLE_RE.match(cell_a)
        if grid_match:
            day = grid_match.group(1).lower()
            i = _parse_grid(day, rows, i + 1, result)
            continue

        # Check if this row starts a section
        section = _detect_section(cell_a)
        if section:
            i = _parse_section(section, rows, i, result)
            continue

        # Unrecognized row — skip
        i += 1

    return result


def _detect_section(cell_a: str) -> str | None:
    """Detect if a cell indicates the start of a known section."""
    for section in _SECTION_HEADERS:
        if cell_a.startswith(section):
            return section
    return None


def _parse_section(
    section: str, rows: list[list[str]], start: int, result: dict
) -> int:
    """Parse a table section. Returns the next row index to process."""
    # Skip the description row
    i = start + 1

    if section == "battle_outcome_matrix":
        # Grids are parsed by the main loop via grid title detection
        return i

    # Next non-blank row should be column headers — skip it
    while i < len(rows) and _is_blank_row(rows[i]):
        i += 1
    if i >= len(rows):
        return i
    # This is the column headers row — skip it
    i += 1

    if section == "default_targets":
        return _parse_default_targets(rows, i, result)
    elif section == "event_targets":
        return _parse_event_targets(rows, i, result)
    return i


def _parse_default_targets(
    rows: list[list[str]], i: int, result: dict
) -> int:
    """Parse default_targets data rows."""
    targets: dict[str, dict] = {}

    while i < len(rows):
        row = rows[i]
        cell_a = _cell(row, 0).strip()

        if _is_blank_row(row) or _is_new_section(cell_a):
            break

        alliance = cell_a
        type_ = _cell(row, 1).strip()
        value = _cell(row, 2).strip()

        if not type_ or not value:
            i += 1
            continue

        if type_ == "target":
            targets[alliance] = {"target": value}
        elif type_ == "strategy":
            targets[alliance] = {"strategy": value}

        i += 1

    if targets:
        result["default_targets"] = targets
    return i


def _parse_event_targets(
    rows: list[list[str]], i: int, result: dict
) -> int:
    """Parse event_targets data rows."""
    targets: dict[str, dict[str, str | dict]] = {}

    while i < len(rows):
        row = rows[i]
        cell_a = _cell(row, 0).strip()

        if _is_blank_row(row) or _is_new_section(cell_a):
            break

        event = cell_a
        alliance = _cell(row, 1).strip()
        type_ = _cell(row, 2).strip()
        value = _cell(row, 3).strip()

        if not type_ or not value:
            i += 1
            continue

        event_dict = targets.setdefault(event, {})
        if type_ == "target":
            event_dict[alliance] = {"target": value}
        elif type_ == "strategy":
            event_dict[alliance] = {"strategy": value}

        i += 1

    if targets:
        result["event_targets"] = targets
    return i


def _parse_grid(
    day: str, rows: list[list[str]], i: int, result: dict
) -> int:
    """Parse a single probability grid after its title row."""
    # Skip blank rows to find header
    while i < len(rows) and _is_blank_row(rows[i]):
        i += 1
    if i >= len(rows):
        return i

    # Header row: first cell is blank/label, rest are defender IDs
    header = rows[i]
    defender_ids: list[tuple[int, str]] = []
    for j in range(1, len(header)):
        did = _cell(header, j).strip()
        if did:
            defender_ids.append((j, did))
    i += 1

    # Data rows
    matrix = result.setdefault("battle_outcome_matrix", {})
    day_matrix = matrix.setdefault(day, {})

    while i < len(rows):
        row = rows[i]
        if _is_blank_row(row):
            i += 1
            break

        cell_a = _cell(row, 0).strip()

        # Stop at next grid title or section
        if _GRID_TITLE_RE.match(cell_a) or _detect_section(cell_a) is not None:
            break

        # Skip comments
        if cell_a.startswith("#"):
            i += 1
            continue

        attacker_id = cell_a
        if not attacker_id:
            i += 1
            continue

        for col_idx, def_id in defender_ids:
            pct_str = _cell(row, col_idx).strip()
            if pct_str:
                try:
                    pct = int(round(float(pct_str)))
                    day_matrix.setdefault(attacker_id, {})[def_id] = {
                        "full_success": pct / 100,
                    }
                except ValueError:
                    pass

        i += 1

    return i


def _cell(row: list[str], index: int) -> str:
    """Safely get a cell value, returning empty string if out of range."""
    if index < len(row):
        return row[index]
    return ""


def _is_blank_row(row: list[str]) -> bool:
    """Check if a row is entirely blank."""
    return all(c.strip() == "" for c in row)


def _is_new_section(cell_a: str) -> bool:
    """Check if cell_a indicates the start of a new known section."""
    return _detect_section(cell_a) is not None or _GRID_TITLE_RE.match(cell_a) is not None
