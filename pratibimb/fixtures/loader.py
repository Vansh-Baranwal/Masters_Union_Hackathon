"""
Fixture loader — reads fixture JSON files and returns typed InterpretationRecord objects.
Used in tests and in the demo seeding script.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from intake.models import InterpretationRecord, ExtractedFields, ScreenshotType

FIXTURES_DIR = Path(__file__).parent


def load_fixture(name: str) -> InterpretationRecord:
    """
    Load a fixture by filename (with or without .json extension).
    Returns a fully typed InterpretationRecord.
    """
    if not name.endswith(".json"):
        name = name + ".json"
    path = FIXTURES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Fixture not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    # Strip internal scenario notes
    data.pop("_scenario", None)
    fields_dict = data.pop("fields", {})
    fields = ExtractedFields(**{k: v for k, v in fields_dict.items() if k in ExtractedFields.model_fields})
    return InterpretationRecord(
        **{k: v for k, v in data.items() if k in InterpretationRecord.model_fields},
        fields=fields,
    )


def load_all_fixtures() -> list[InterpretationRecord]:
    """Load every .json fixture in the fixtures directory."""
    records = []
    for path in sorted(FIXTURES_DIR.glob("*.json")):
        try:
            records.append(load_fixture(path.name))
        except Exception as exc:
            print(f"Warning: could not load {path.name}: {exc}")
    return records


def fixture_names() -> list[str]:
    return [p.stem for p in sorted(FIXTURES_DIR.glob("*.json"))]
