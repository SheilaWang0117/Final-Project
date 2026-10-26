"""Model provider setup. No silent provider or model switching.

- LLM_PROVIDER=portkey: course key via the Portkey gateway, gpt-6-luna only.
- LLM_PROVIDER=openai: a personal OpenAI key with an explicitly set OPENAI_MODEL.
If the selected provider is not ready, live agent calls fail with a clear
message; they never fall back to another provider or model.

The Responses API is used because the gateway rejects function tools with
reasoning on /chat/completions for this model.
"""

from __future__ import annotations

import contextvars
import json
import os
from decimal import Decimal
from pathlib import Path

import httpx2

from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from ..config import PORTKEY_BASE_URL, PORTKEY_MODEL, get_settings

PRICING_PATH = Path(__file__).resolve().parent / "pricing.json"


class ProviderNotReady(RuntimeError):
    pass


# Collects x-portkey-cache-status values for the agent run in the current context.
GATEWAY_CACHE: contextvars.ContextVar[list | None] = contextvars.ContextVar("gateway_cache", default=None)


async def _record_gateway_cache(response) -> None:
    statuses = GATEWAY_CACHE.get()
    status = response.headers.get("x-portkey-cache-status")
    if statuses is not None and status:
        statuses.append(status.upper())


def _http_client(timeout: float) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(timeout=timeout, event_hooks={"response": [_record_gateway_cache]})


def build_model() -> OpenAIResponsesModel:
    s = get_settings()
    if s.errors:
        raise ProviderNotReady("; ".join(s.errors))
    if s.is_demo:
        raise ProviderNotReady("Demo mode does not call models. Set APP_MODE=live to enable live agents.")
    if s.llm_provider == "portkey":
        key = os.getenv("PORTKEY_API_KEY")
        if not key:
            raise ProviderNotReady("PORTKEY_API_KEY is not set (checked environment, repo .env, and parent .env).")
        headers = {"x-portkey-api-key": key}
        if (os.getenv("PORTKEY_CACHE_FORCE_REFRESH") or "").lower() in ("1", "true", "yes"):
            headers["x-portkey-cache-force-refresh"] = "true"  # bypass the gateway response cache (used in evaluations)
        client = AsyncOpenAI(api_key=key, base_url=PORTKEY_BASE_URL, default_headers=headers, max_retries=1,
                             timeout=s.run_timeout_seconds, http_client=_http_client(s.run_timeout_seconds))
        return OpenAIResponsesModel(PORTKEY_MODEL, provider=OpenAIProvider(openai_client=client))
    if s.llm_provider == "openai":
        key = os.getenv("OPENAI_API_KEY")
        if not key or not s.model_name:
            raise ProviderNotReady("LLM_PROVIDER=openai requires OPENAI_API_KEY and OPENAI_MODEL.")
        client = AsyncOpenAI(api_key=key, max_retries=1, timeout=s.run_timeout_seconds)
        return OpenAIResponsesModel(s.model_name, provider=OpenAIProvider(openai_client=client))
    raise ProviderNotReady("LLM_PROVIDER=none: live model calls are disabled.")


def pricing() -> dict:
    try:
        return json.loads(PRICING_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"models": {}}


def estimate_cost(model: str | None, input_tokens: int, cached_input_tokens: int, output_tokens: int) -> tuple[str | None, str | None]:
    """Return (cost_usd as decimal string, pricing_version) or (None, None) if unknown.

    Never guesses: if any needed price is missing, the cost is unknown.
    """
    p = pricing()
    entry = p.get("models", {}).get(model or "")
    if not entry:
        return None, None
    try:
        inp = Decimal(str(entry["input_usd_per_mtok"]))
        out = Decimal(str(entry["output_usd_per_mtok"]))
        cached = Decimal(str(entry.get("cached_input_usd_per_mtok", entry["input_usd_per_mtok"])))
    except (KeyError, TypeError, ArithmeticError):
        return None, None
    uncached = max(0, input_tokens - cached_input_tokens)
    cost = (Decimal(uncached) * inp + Decimal(cached_input_tokens) * cached + Decimal(output_tokens) * out) / Decimal(1_000_000)
    return str(cost.quantize(Decimal("0.000001"))), f"{model}@{entry.get('as_of')}"
