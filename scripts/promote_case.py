"""Promotes a failing case into the permanent eval suite.

Two modes:
  1. Pin an existing case's observed regression as a standing regression test.
  2. Add a brand-new case discovered outside the current suite.

Usage:
    python scripts/promote_case.py --from-run runs/change --case-id H4
    python scripts/promote_case.py --question "..." --gold-sql "..." \\
        --category hard --label "..."
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = REPO_ROOT / "evals" / "cases.yaml"


def load_cases() -> list:
    return yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))


def save_cases(cases: list) -> None:
    CASES_PATH.write_text(
        yaml.safe_dump(cases, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )


def next_regression_id(cases: list) -> str:
    n = sum(1 for c in cases if c["id"].startswith("REG")) + 1
    return f"REG{n}"


def promote_from_run(run_dir: Path, case_id: str) -> dict:
    trace = json.loads((run_dir / "traces" / f"{case_id}.json").read_text(encoding="utf-8"))
    cases = load_cases()
    source = next((c for c in cases if c["id"] == case_id), None)
    if source is None:
        raise SystemExit(f"case {case_id} not found in {CASES_PATH}")

    new_case = dict(source)
    new_case["id"] = next_regression_id(cases)
    new_case["origin"] = {
        "promoted_from": case_id,
        "source_run": run_dir.name,
        "promoted_at": datetime.now(timezone.utc).isoformat(),
        "observed_failure": trace.get("execution_error") or trace.get("model_grade_rationale"),
    }
    cases.append(new_case)
    save_cases(cases)
    return new_case


def promote_adhoc(question: str, gold_sql: str, category: str, label: str, should_refuse: bool) -> dict:
    cases = load_cases()
    new_case = {
        "id": next_regression_id(cases),
        "category": category,
        "question": question,
        "gold_sql": gold_sql,
        "should_refuse": should_refuse,
        "label": label,
        "origin": {"promoted_at": datetime.now(timezone.utc).isoformat(), "source": "manual/production"},
    }
    cases.append(new_case)
    save_cases(cases)
    return new_case


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from-run", help="Path to a run directory, e.g. runs/change")
    parser.add_argument("--case-id", help="Case id to promote from that run")
    parser.add_argument("--question")
    parser.add_argument("--gold-sql")
    parser.add_argument("--category", choices=["easy", "medium", "hard", "refusal"])
    parser.add_argument("--label")
    parser.add_argument("--should-refuse", action="store_true")
    args = parser.parse_args()

    if args.from_run:
        if not args.case_id:
            raise SystemExit("--case-id is required with --from-run")
        new_case = promote_from_run(Path(args.from_run), args.case_id)
    else:
        if not (args.question and args.category and args.label):
            raise SystemExit("--question, --category and --label are required for ad-hoc promotion")
        new_case = promote_adhoc(args.question, args.gold_sql, args.category, args.label, args.should_refuse)

    print(f"Promoted new permanent eval case: {new_case['id']}")
    print(json.dumps(new_case, indent=2))


if __name__ == "__main__":
    main()
