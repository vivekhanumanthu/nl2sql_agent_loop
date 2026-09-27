"""Model-graded check: judges the agent's behaviour against a human-written
label, as a complement to the exact-match execution grader (e.g. it catches
a wrongful refusal, which execution accuracy would just see as "no SQL").

With provider: openai this sends a real grading prompt to an LLM judge. With
the default mock provider it falls back to a deterministic heuristic instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from agent.llm_client import get_provider

JUDGE_SYSTEM_PROMPT = """You are grading an AI agent that turns questions into SQL.
You are given: the question, a human-written label describing what a correct answer
must do, whether the agent should have refused, whether it refused, the SQL it wrote,
and whether that SQL executed to the same rows as a trusted gold query.
Respond with exactly one line: "PASS" or "FAIL", followed by a short reason."""


@dataclass
class ModelGradeResult:
    passed: bool
    rationale: str


def grade_with_model(
    *,
    provider_name: str,
    question: str,
    label: str,
    should_refuse: bool,
    refused: bool,
    sql: Optional[str],
    execution_passed: Optional[bool],
    seed: int = 0,
    judge_model: str = "judge",
    base_url: Optional[str] = None,
    api_key_env: str = "OPENAI_API_KEY",
) -> ModelGradeResult:
    if provider_name == "mock":
        return _heuristic_judge(should_refuse, refused, execution_passed)

    provider = get_provider(provider_name, base_url=base_url, api_key_env=api_key_env)
    user_prompt = (
        f"Question: {question}\n"
        f"Label (ground truth criteria): {label}\n"
        f"Should the agent have refused?: {should_refuse}\n"
        f"Did the agent refuse?: {refused}\n"
        f"Agent SQL: {sql!r}\n"
        f"Execution accuracy result: {execution_passed}\n"
    )
    resp = provider.complete(
        JUDGE_SYSTEM_PROMPT, user_prompt, model=judge_model, temperature=0.0, seed=seed, max_tokens=200
    )
    text = resp.text.strip()
    match = re.match(r"\s*(PASS|FAIL)\b[:\-\s]*(.*)", text, re.IGNORECASE | re.DOTALL)
    if not match:
        return ModelGradeResult(False, f"unparseable judge output: {text[:200]}")
    return ModelGradeResult(match.group(1).upper() == "PASS", match.group(2).strip() or text)


def _heuristic_judge(should_refuse: bool, refused: bool, execution_passed: Optional[bool]) -> ModelGradeResult:
    if should_refuse:
        passed = refused
        reason = "agent correctly refused" if passed else "agent should have refused but did not"
        return ModelGradeResult(passed, reason)
    if refused:
        return ModelGradeResult(False, "agent refused a legitimate, answerable question")
    passed = bool(execution_passed)
    reason = "execution matched gold result" if passed else "execution result diverged from gold"
    return ModelGradeResult(passed, reason)
