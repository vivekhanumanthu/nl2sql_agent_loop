"""Runs one agent config against the eval suite and records latency, tokens,
cost and a per-case trace to disk, so any run can be diffed, gated or
reported on later.

Usage:
    python -m runner.run_eval --config configs/agent_v1.yaml --run-id baseline
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import yaml

from agent.nl2sql_agent import AgentConfig, NL2SQLAgent
from graders.execution_grader import grade_execution
from graders.model_grader import grade_with_model

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_cases(path: Path) -> list:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def run_one(agent: NL2SQLAgent, case: dict, db_path: str, provider_name: str, judge_seed: int) -> dict:
    t0 = time.perf_counter()
    result = agent.answer(case["question"])
    wall_ms = (time.perf_counter() - t0) * 1000

    should_refuse = bool(case.get("should_refuse", False))
    execution_passed = None
    exec_error = None
    if not should_refuse:
        exec_result = grade_execution(db_path, result.sql, case["gold_sql"])
        execution_passed = exec_result.passed
        exec_error = exec_result.error

    judge = grade_with_model(
        provider_name=provider_name,
        question=case["question"],
        label=case["label"],
        should_refuse=should_refuse,
        refused=result.refused,
        sql=result.sql,
        execution_passed=execution_passed,
        seed=judge_seed,
        judge_model=agent.config.judge_model,
        base_url=agent.config.base_url,
        api_key_env=agent.config.api_key_env,
    )

    case_passed = result.refused if should_refuse else bool(execution_passed) and judge.passed

    return {
        "id": case["id"],
        "category": case["category"],
        "question": case["question"],
        "should_refuse": should_refuse,
        "refused": result.refused,
        "sql": result.sql,
        "raw_response": result.raw_response,
        "execution_passed": execution_passed,
        "execution_error": exec_error,
        "model_grade_passed": judge.passed,
        "model_grade_rationale": judge.rationale,
        "passed": case_passed,
        "latency_ms": round(result.latency_ms, 2),
        "wall_ms": round(wall_ms, 2),
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cost_usd": round(result.cost_usd, 8),
    }


def run_suite(config_path: str, cases_path: str, db_path: str, concurrency: int) -> list:
    config = AgentConfig.load(config_path)
    agent = NL2SQLAgent(config, db_path)
    cases = load_cases(REPO_ROOT / cases_path)

    results = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(run_one, agent, case, db_path, config.provider, config.seed): case for case in cases
        }
        for fut in as_completed(futures):
            results.append(fut.result())
    results.sort(key=lambda r: r["id"])
    return results, config


def summarize(run_id: str, config_path: str, config, results: list) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r["passed"])

    by_category: dict = {}
    for r in results:
        c = by_category.setdefault(r["category"], {"total": 0, "passed": 0})
        c["total"] += 1
        c["passed"] += int(r["passed"])
    for c in by_category.values():
        c["pass_rate"] = round(c["passed"] / c["total"], 4)

    latencies = sorted(r["latency_ms"] for r in results)
    p95_idx = min(len(latencies) - 1, int(0.95 * len(latencies)))

    return {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config_path": Path(config_path).as_posix(),
        "config_version": config.version,
        "config_hash": config.config_hash(),
        "model": config.model,
        "provider": config.provider,
        "total_cases": total,
        "passed_cases": passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "by_category": by_category,
        "total_cost_usd": round(sum(r["cost_usd"] for r in results), 8),
        "avg_latency_ms": round(statistics.mean(latencies), 2) if latencies else 0.0,
        "p50_latency_ms": round(statistics.median(latencies), 2) if latencies else 0.0,
        "p95_latency_ms": round(latencies[p95_idx], 2) if latencies else 0.0,
        "total_input_tokens": sum(r["input_tokens"] for r in results),
        "total_output_tokens": sum(r["output_tokens"] for r in results),
    }


def main():
    parser = argparse.ArgumentParser(description="Run the NL2SQL eval suite against one config version.")
    parser.add_argument("--config", required=True, help="Path to configs/agent_*.yaml")
    parser.add_argument("--cases", default="evals/cases.yaml")
    parser.add_argument("--db", default="data/chinook.db")
    parser.add_argument("--run-id", required=True, help="Name for this run, e.g. baseline / change")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--out-dir", default="runs")
    args = parser.parse_args()

    results, config = run_suite(args.config, args.cases, args.db, args.concurrency)

    run_dir = REPO_ROOT / args.out_dir / args.run_id
    traces_dir = run_dir / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    for r in results:
        (traces_dir / f"{r['id']}.json").write_text(json.dumps(r, indent=2), encoding="utf-8")

    summary = summarize(args.run_id, args.config, config, results)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (run_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    main()
