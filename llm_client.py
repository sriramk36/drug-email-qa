"""
Thin LLM client wrapper.

Defaults to Azure AI Foundry (matches the GPT-4o-mini deployment
you're already using for Orbit SDR) since it's OpenAI-wire-compatible.
Falls back to the Anthropic API if ANTHROPIC_API_KEY is set instead.
Swap this out freely — nothing else in the pipeline cares which
provider answered, only that it gets back a string of HTML.

TOKEN COST NOTE (why this file cares about prompt caching):
`generator.py`'s SYSTEM_PROMPT is loaded once and reused byte-for-byte
on every call, for every brand/market, forever — it's deliberately
market-agnostic (market-specific content goes in the per-call user
prompt instead, see regulatory.py::market_addendum). That makes it an
ideal cache target:

- Anthropic: caching is opt-in via `cache_control`. This client tags
  the system prompt with `{"type": "ephemeral"}` on every call. The
  first call pays a small write premium (1.25x input rate); every call
  after that within the cache window reads it at ~10% of normal input
  price — a ~90% discount on the ~1000 tokens of system prompt, on
  every single generate/revise call in every pipeline run.
- Azure AI Foundry / OpenAI-compatible: caching is automatic, no code
  needed, for prompts >=1024 tokens with an identical prefix — which
  is exactly why generator_system.md wasn't trimmed down aggressively
  when asked to optimize tokens. Shrinking it below ~1024 tokens would
  drop it out of Azure's auto-cache eligibility and could cost more
  overall even though the raw prompt looks shorter.

Env vars (Azure path):
    AZURE_AI_FOUNDRY_ENDPOINT   e.g. https://<resource>.services.ai.azure.com/models
    AZURE_AI_FOUNDRY_API_KEY
    AZURE_AI_FOUNDRY_DEPLOYMENT e.g. gpt-4o-mini

Env vars (Anthropic path, used only if the Azure ones are absent):
    ANTHROPIC_API_KEY
    ANTHROPIC_MODEL             defaults to claude-sonnet-4-6
"""

from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

class LLMClient:
    def __init__(self):
        self.provider = None
        self.last_usage = None  # populated after each complete() call; pipeline.py can log it
        if os.getenv("AZURE_AI_FOUNDRY_ENDPOINT") and os.getenv("AZURE_AI_FOUNDRY_API_KEY"):
            self.provider = "azure"
            from openai import OpenAI  # Azure AI Foundry's chat-completions route is OpenAI-wire-compatible
            self._client = OpenAI(
                base_url=os.environ["AZURE_AI_FOUNDRY_ENDPOINT"],
                api_key=os.environ["AZURE_AI_FOUNDRY_API_KEY"],
            )
            self._deployment = os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT", "gpt-4o-mini")
        elif os.getenv("ANTHROPIC_API_KEY"):
            self.provider = "anthropic"
            import anthropic
            self._client = anthropic.Anthropic()
            self._model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        else:
            raise RuntimeError(
                "No LLM credentials found. Set AZURE_AI_FOUNDRY_ENDPOINT + "
                "AZURE_AI_FOUNDRY_API_KEY, or ANTHROPIC_API_KEY, as environment variables."
            )

    def complete(self, system: str, user: str, max_tokens: int = 4000) -> str:
        if self.provider == "azure":
            # No cache_control needed — Azure/OpenAI-compatible caching is automatic
            # on a repeated prefix over ~1024 tokens. Just don't reorder or reformat
            # `system` between calls, or the prefix stops matching and the discount
            # silently disappears.
            resp = self._client.chat.completions.create(
                model=self._deployment,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
                temperature=0.4,
            )
            self.last_usage = resp.usage.model_dump() if resp.usage else None
            return resp.choices[0].message.content
        else:  # anthropic
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
            )
            usage = resp.usage
            self.last_usage = {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0),
                "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0),
            }
            return "".join(b.text for b in resp.content if b.type == "text")
