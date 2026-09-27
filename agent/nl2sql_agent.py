"""The NL2SQL agent under test: a thin wrapper around an LLM provider.
Prompt, model, temperature, seed and pricing all come from a versioned
config file (configs/agent_*.yaml) - not from this module.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from agent.llm_client import get_provider
from agent.schema import get_schema_description

SQL_BLOCK_RE = re.compile(r"```sql\s*(.*?)```", re.IGNORECASE | re.DOTALL)
REFUSE_RE = re.compile(r"^\s*REFUSE:\s*(.*)$", re.IGNORECASE | re.DOTALL)


@dataclass
class AgentConfig:
    path: Path
    name: str
    version: str
    provider: str
    model: str
    base_url: Optional[str]
    api_key_env: str
    judge_model: str
    temperature: float
    seed: int
    max_tokens: int
    system_prompt: str
    input_price_per_1k: float
    output_price_per_1k: float

    @classmethod
    def load(cls, path: str) -> "AgentConfig":
        path_obj = Path(path)
        raw = yaml.safe_load(path_obj.read_text(encoding="utf-8"))
        model_cfg = raw["model"]
        pricing = raw.get("pricing", {})
        return cls(
            path=path_obj,
            name=raw.get("name", path_obj.stem),
            version=raw.get("version", path_obj.stem),
            provider=model_cfg.get("provider", "mock"),
            model=model_cfg["name"],
            base_url=model_cfg.get("base_url"),
            api_key_env=model_cfg.get("api_key_env", "OPENAI_API_KEY"),
            judge_model=model_cfg.get("judge_model", model_cfg["name"]),
            temperature=float(model_cfg.get("temperature", 0.0)),
            seed=int(model_cfg.get("seed", 0)),
            max_tokens=int(model_cfg.get("max_tokens", 512)),
            system_prompt=raw["prompt"]["system"].strip(),
            input_price_per_1k=float(pricing.get("input_per_1k", 0.0)),
            output_price_per_1k=float(pricing.get("output_per_1k", 0.0)),
        )

    def config_hash(self) -> str:
        blob = (
            f"{self.provider}|{self.base_url}|{self.api_key_env}|{self.model}|{self.judge_model}|"
            f"{self.temperature}|{self.seed}|{self.max_tokens}|{self.system_prompt}"
        )
        return hashlib.sha256(blob.encode()).hexdigest()[:12]


@dataclass
class AgentResult:
    question: str
    raw_response: str
    sql: Optional[str]
    refused: bool
    refusal_reason: Optional[str]
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost_usd: float


class NL2SQLAgent:
    def __init__(self, config: AgentConfig, db_path: str):
        self.config = config
        self.db_path = db_path
        self._provider = get_provider(config.provider, base_url=config.base_url, api_key_env=config.api_key_env)
        self._schema = get_schema_description(db_path)

    def answer(self, question: str) -> AgentResult:
        user_prompt = f"Database schema:\n{self._schema}\n\nQuestion: {question}\n"
        resp = self._provider.complete(
            self.config.system_prompt,
            user_prompt,
            model=self.config.model,
            temperature=self.config.temperature,
            seed=self.config.seed,
            max_tokens=self.config.max_tokens,
        )
        sql, refused, reason = self._parse(resp.text)
        cost = (
            resp.input_tokens / 1000 * self.config.input_price_per_1k
            + resp.output_tokens / 1000 * self.config.output_price_per_1k
        )
        return AgentResult(
            question=question,
            raw_response=resp.text,
            sql=sql,
            refused=refused,
            refusal_reason=reason,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
            latency_ms=resp.latency_ms,
            cost_usd=cost,
        )

    @staticmethod
    def _parse(text: str):
        refuse_match = REFUSE_RE.match(text.strip())
        if refuse_match:
            return None, True, refuse_match.group(1).strip()
        sql_match = SQL_BLOCK_RE.search(text)
        if sql_match:
            return sql_match.group(1).strip(), False, None
        # no SQL block or REFUSE marker -> fail safe as an unmarked refusal
        return None, True, text.strip()
