from __future__ import annotations

import json
from pathlib import Path

import jsonschema

DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schema" / "repo_health.schema.json"


def load_schema(path: Path = DEFAULT_SCHEMA_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_record(record: dict, schema: dict | None = None) -> list[str]:
    """Returns a list of human-readable validation error messages (empty = valid)."""
    schema = schema or load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    return [f"{'/'.join(str(p) for p in err.path) or '<root>'}: {err.message}" for err in validator.iter_errors(record)]
