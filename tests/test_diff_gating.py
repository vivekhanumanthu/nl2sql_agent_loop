from runner.diff import gate


def test_gate_fails_on_regression():
    diff = {"regressions": [{"id": "X"}], "candidate_pass_rate": 1.0, "cost_change_pct": 0, "p95_latency_change_pct": 0}
    thresholds = {"max_regressions": 0, "min_pass_rate": 0.8}
    assert gate(diff, thresholds)


def test_gate_passes_when_clean():
    diff = {"regressions": [], "candidate_pass_rate": 1.0, "cost_change_pct": 0, "p95_latency_change_pct": 0}
    thresholds = {"max_regressions": 0, "min_pass_rate": 0.8}
    assert gate(diff, thresholds) == []


def test_gate_fails_on_low_pass_rate():
    diff = {"regressions": [], "candidate_pass_rate": 0.5, "cost_change_pct": 0, "p95_latency_change_pct": 0}
    thresholds = {"max_regressions": 0, "min_pass_rate": 0.8}
    assert gate(diff, thresholds)


def test_gate_fails_on_cost_spike():
    diff = {"regressions": [], "candidate_pass_rate": 1.0, "cost_change_pct": 300, "p95_latency_change_pct": 0}
    thresholds = {"max_regressions": 0, "min_pass_rate": 0.8, "max_cost_increase_pct": 100}
    assert gate(diff, thresholds)
