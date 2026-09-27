"""LLM provider abstraction. Which provider runs is a config value
(model.provider in configs/agent_*.yaml), never a code change.
"""
from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass

from dotenv import load_dotenv

from agent.mock_kb import mock_respond

load_dotenv()  # Load provider credentials from the local environment file.


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: float


class BaseProvider:
    def complete(
        self, system_prompt: str, user_prompt: str, *, model: str, temperature: float, seed: int, max_tokens: int
    ) -> LLMResponse:
        raise NotImplementedError


class OpenAIProvider(BaseProvider):
    """Calls OpenAI or an OpenAI-compatible Chat Completions endpoint.

    Note: OpenAI's `seed` param is best-effort, unlike the mock provider exact
    reproducibility across runs isn't guaranteed.
    """

    # OPENAI_API_KEY may hold a Groq key when base_url points to Groq.

    def __init__(self, *, base_url=None, api_key_env="OPENAI_API_KEY"):
        from openai import OpenAI  # lazy import so mock mode doesn't need this installed/configured

        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(
                f"{api_key_env} is not set. Add it to your local .env file or export it in your shell."
            )
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def complete(self, system_prompt, user_prompt, *, model, temperature, seed, max_tokens):
        start = time.perf_counter()
        resp = self._client.chat.completions.create(
            model=model,
            temperature=temperature,
            seed=seed,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        latency_ms = (time.perf_counter() - start) * 1000
        text = resp.choices[0].message.content or ""
        usage = resp.usage
        return LLMResponse(
            text=text,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            latency_ms=latency_ms,
        )


class MockProvider(BaseProvider):
    """Deterministic offline provider - see agent/mock_kb.py."""

    def complete(self, system_prompt, user_prompt, *, model, temperature, seed, max_tokens):
        rng = random.Random(f"{seed}:{model}:{user_prompt}")
        start = time.perf_counter()
        # match only the question text, not the schema dump also in user_prompt
        # (table names like "Playlist" would otherwise leak "list" as a false match)
        marker = "Question:"
        idx = user_prompt.rfind(marker)
        question = user_prompt[idx + len(marker):].strip() if idx != -1 else user_prompt
        text = mock_respond(question, system_prompt, rng)
        # base latency + small seeded jitter, deterministic per seed
        simulated_latency = 120 + rng.uniform(-20, 60) + (40 if temperature > 0.3 else 0)
        elapsed_wall = (time.perf_counter() - start) * 1000
        latency_ms = simulated_latency + elapsed_wall
        input_tokens = max(1, len(system_prompt.split()) + len(user_prompt.split()))
        output_tokens = max(1, len(text.split()))
        return LLMResponse(text=text, input_tokens=input_tokens, output_tokens=output_tokens, latency_ms=latency_ms)


def get_provider(name: str, *, base_url=None, api_key_env="OPENAI_API_KEY") -> BaseProvider:
    name = (name or "mock").lower()
    if name == "mock":
        return MockProvider()
    if name in ("openai", "azure_openai"):
        return OpenAIProvider(base_url=base_url, api_key_env=api_key_env)
    if name == "openai_compatible":
        if not base_url:
            raise ValueError("model.base_url is required when model.provider is openai_compatible")
        return OpenAIProvider(base_url=base_url, api_key_env=api_key_env)
    raise ValueError(f"Unknown provider: {name}")
