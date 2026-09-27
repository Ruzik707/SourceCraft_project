import json
from pathlib import Path

from collector.schema_validate import validate_record

EXAMPLE_PATH = Path(__file__).resolve().parents[1] / "schema" / "examples" / "example_repo_health.json"


def test_example_record_matches_schema():
    record = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    problems = validate_record(record)
    assert problems == []
