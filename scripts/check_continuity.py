"""Check the two-chapter continuity eval on finished runs. Free: no model calls.

    uv run python scripts/check_continuity.py chapter-1-the-reunion chapter-2-the-rooftop

Writes smoke_results/continuity-<chapter-2 id>.json and exits 1 if any check fails.
"""

import json
import sys
from pathlib import Path

import yaml

from comartist.config import Settings
from comartist.tools.continuity_check import ContinuityExpectations, check_continuity
from comartist.workflows.store import RunStore

EXPECTATIONS = Path(__file__).resolve().parent.parent / "evals" / "continuity" / "expectations.yaml"


def main(first_id: str, second_id: str) -> int:
    store = RunStore(Settings().runs_dir)
    expect = ContinuityExpectations.model_validate(yaml.safe_load(EXPECTATIONS.read_text()))
    checks = check_continuity(store.load(first_id), store.load(second_id), expect)
    for check in checks:
        print(f"{'PASS' if check.passed else 'FAIL'}  {check.name}  ({check.evidence})")
    out = Path("smoke_results") / f"continuity-{second_id}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(
        {"first": first_id, "second": second_id, "checks": [check.model_dump() for check in checks]}, indent=2,
    ))
    passed = sum(check.passed for check in checks)
    print(f"\n{passed}/{len(checks)} checks passed -> {out}")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
