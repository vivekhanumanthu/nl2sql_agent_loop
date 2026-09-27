"""Generates a static HTML report from every run under runs/: pass rate over
time, cost/latency trends, category breakdown, and a per-case drill-down.

Usage:
    python -m report.generate_report
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = REPO_ROOT / "runs"
OUT_PATH = REPO_ROOT / "report" / "index.html"


def load_runs():
    runs = []
    for run_dir in sorted(RUNS_DIR.iterdir()):
        summary_path = run_dir / "summary.json"
        results_path = run_dir / "results.json"
        if not summary_path.exists():
            continue
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        results = json.loads(results_path.read_text(encoding="utf-8")) if results_path.exists() else []
        runs.append((summary, results))
    runs.sort(key=lambda sr: sr[0]["timestamp"])
    return runs


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render(runs) -> str:
    labels = [s["run_id"] for s, _ in runs]
    pass_rates = [round(s["pass_rate"] * 100, 1) for s, _ in runs]
    costs = [s["total_cost_usd"] for s, _ in runs]
    p95s = [s["p95_latency_ms"] for s, _ in runs]

    category_rows = []
    for s, _ in runs:
        for cat, stats in s.get("by_category", {}).items():
            category_rows.append(
                f"<tr><td>{s['run_id']}</td><td>{cat}</td><td>{stats['passed']}/{stats['total']}</td>"
                f"<td>{stats['pass_rate']:.0%}</td></tr>"
            )

    drilldowns = []
    for s, results in runs:
        rows = []
        for r in results:
            status = "PASS" if r["passed"] else "FAIL"
            rows.append(
                "<tr>"
                f"<td>{r['id']}</td><td>{r['category']}</td><td class=\"{status.lower()}\">{status}</td>"
                f"<td>{r['latency_ms']:.0f} ms</td><td>${r['cost_usd']:.6f}</td>"
                f"<td><details><summary>trace</summary><pre>{_escape(json.dumps(r, indent=2))}</pre></details></td>"
                "</tr>"
            )
        drilldowns.append(
            f"<h3>{s['run_id']} &mdash; {s['config_version']} ({s['passed_cases']}/{s['total_cases']} passed, "
            f"${s['total_cost_usd']:.6f}, p95 {s['p95_latency_ms']:.0f} ms)</h3>"
            "<table><tr><th>id</th><th>category</th><th>status</th><th>latency</th><th>cost</th><th>trace</th></tr>"
            + "".join(rows)
            + "</table>"
        )

    return HTML_TEMPLATE.format(
        labels=json.dumps(labels),
        pass_rates=json.dumps(pass_rates),
        costs=json.dumps(costs),
        p95s=json.dumps(p95s),
        category_rows="".join(category_rows),
        drilldowns="".join(drilldowns),
    )


HTML_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>NL2SQL Eval Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1a1a1a; }}
table {{ border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; }}
th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; font-size: 14px; }}
th {{ background: #f4f4f4; }}
td.pass {{ color: #16a34a; font-weight: 600; }}
td.fail {{ color: #dc2626; font-weight: 600; }}
pre {{ white-space: pre-wrap; font-size: 12px; background: #fafafa; padding: 8px; }}
canvas {{ max-width: 700px; }}
h1, h2 {{ margin-top: 2rem; }}
</style>
</head>
<body>
<h1>NL2SQL Continuous Eval Report</h1>

<h2>Pass rate over time</h2>
<canvas id="passRateChart"></canvas>

<h2>Cost &amp; p95 latency over time</h2>
<canvas id="costLatencyChart"></canvas>

<h2>Breakdown by category</h2>
<table><tr><th>run</th><th>category</th><th>passed</th><th>pass rate</th></tr>{category_rows}</table>

<h2>Drill-down</h2>
{drilldowns}

<script>
const labels = {labels};
new Chart(document.getElementById('passRateChart'), {{
  type: 'line',
  data: {{ labels, datasets: [{{ label: 'Pass rate (%)', data: {pass_rates}, borderColor: '#2563eb', tension: 0.2 }}] }},
  options: {{ scales: {{ y: {{ min: 0, max: 100 }} }} }}
}});
new Chart(document.getElementById('costLatencyChart'), {{
  type: 'line',
  data: {{ labels, datasets: [
    {{ label: 'Total cost (USD)', data: {costs}, borderColor: '#16a34a', yAxisID: 'cost' }},
    {{ label: 'p95 latency (ms)', data: {p95s}, borderColor: '#dc2626', yAxisID: 'latency' }}
  ] }},
  options: {{ scales: {{ cost: {{ type: 'linear', position: 'left' }}, latency: {{ type: 'linear', position: 'right' }} }} }}
}});
</script>
</body>
</html>
"""


def main():
    runs = load_runs()
    if not runs:
        raise SystemExit("No runs found under runs/. Run the runner first.")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(render(runs), encoding="utf-8")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
