"""Diffs a candidate run against a baseline, flags regressions, and gates on
thresholds.yaml. Exit code 1 on gate failure - this is what CI calls.

Usage:
    python -m runner.diff --baseline runs/baseline --candidate runs/change --thresholds thresholds.yaml
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_run(run_dir: Path):
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    return summary, {r["id"]: r for r in results}


def diff_runs(baseline_dir: Path, candidate_dir: Path) -> dict:
    base_summary, base_by_id = load_run(baseline_dir)
    cand_summary, cand_by_id = load_run(candidate_dir)

    regressions, fixes, unchanged = [], [], []
    for cid in sorted(set(base_by_id) | set(cand_by_id)):
        b = base_by_id.get(cid)
        c = cand_by_id.get(cid)
        if b is None or c is None:
            continue  # case only exists in one run (new/removed) - not a regression signal
        if b["passed"] and not c["passed"]:
            regressions.append(
                {
                    "id": cid,
                    "category": c["category"],
                    "question": c["question"],
                    "reason": c.get("execution_error") or c.get("model_grade_rationale"),
                }
            )
        elif not b["passed"] and c["passed"]:
            fixes.append({"id": cid, "category": c["category"]})
        else:
            unchanged.append(cid)

    def pct_change(base: float, cand: float) -> float:
        if base == 0:
            return 0.0 if cand == 0 else float("inf")
        return (cand - base) / base * 100

    return {
        "baseline_run": base_summary["run_id"],
        "candidate_run": cand_summary["run_id"],
        "baseline_pass_rate": base_summary["pass_rate"],
        "candidate_pass_rate": cand_summary["pass_rate"],
        "pass_rate_delta": round(cand_summary["pass_rate"] - base_summary["pass_rate"], 4),
        "cost_change_pct": round(pct_change(base_summary["total_cost_usd"], cand_summary["total_cost_usd"]), 2),
        "p95_latency_change_pct": round(
            pct_change(base_summary["p95_latency_ms"], cand_summary["p95_latency_ms"]), 2
        ),
        "regressions": regressions,
        "fixes": fixes,
        "unchanged_count": len(unchanged),
    }


def gate(diff: dict, thresholds: dict) -> list:
    failures = []
    max_regressions = thresholds.get("max_regressions", 0)
    if len(diff["regressions"]) > max_regressions:
        failures.append(f"{len(diff['regressions'])} regression(s) found (max allowed: {max_regressions})")

    min_pass_rate = thresholds.get("min_pass_rate", 0.0)
    if diff["candidate_pass_rate"] < min_pass_rate:
        failures.append(f"candidate pass rate {diff['candidate_pass_rate']:.2%} below min {min_pass_rate:.2%}")

    max_cost = thresholds.get("max_cost_increase_pct")
    if max_cost is not None and diff["cost_change_pct"] > max_cost:
        failures.append(f"cost increased {diff['cost_change_pct']:.1f}% (max allowed {max_cost}%)")

    max_lat = thresholds.get("max_p95_latency_increase_pct")
    if max_lat is not None and diff["p95_latency_change_pct"] > max_lat:
        failures.append(f"p95 latency increased {diff['p95_latency_change_pct']:.1f}% (max allowed {max_lat}%)")

    return failures


def main():
    parser = argparse.ArgumentParser(description="Diff a candidate run against a baseline and gate on thresholds.")
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--thresholds", default="thresholds.yaml")
    parser.add_argument("--out", default=None, help="Optional path to write the diff JSON to")
    args = parser.parse_args()

    thresholds = yaml.safe_load(Path(args.thresholds).read_text(encoding="utf-8"))
    diff = diff_runs(REPO_ROOT / args.baseline, REPO_ROOT / args.candidate)
    failures = gate(diff, thresholds)
    diff["gate_failures"] = failures
    diff["gate_passed"] = not failures

    text = json.dumps(diff, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")

    if failures:
        print("\nGATE FAILED:", file=sys.stderr)
        for f in failures:
            print(f" - {f}", file=sys.stderr)
        sys.exit(1)
    print("\nGate passed.")


if __name__ == "__main__":
    main()
