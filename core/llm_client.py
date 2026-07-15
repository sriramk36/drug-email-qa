"""
Thin LLM client wrapper — Azure OpenAI only, on purpose.

No fallback to another provider if Azure isn't configured, and no
exception-swallowing anywhere in this file: a missing credential or a
failed API call raises immediately. A previous version of this file
tried Azure AI Foundry's endpoint style and then Anthropic as
fallbacks if the primary Azure path wasn't configured — that's gone.
This project has exactly one real credential (a classic Azure OpenAI
resource), so there's exactly one code path, and if it's missing or
broken you'll see a real error, not a silent switch to something else
or a placeholder result.

REASONING MODELS (gpt-5*, o1/o3/o4 series) NEED DIFFERENT PARAMETERS —
this is not optional, Azure rejects the wrong ones outright:
  - `max_tokens` is rejected ("Unsupported parameter: 'max_tokens' is
    not supported with this model. Use 'max_completion_tokens' instead.")
  - `temperature` is also rejected — no custom value accepted.
  - They spend hidden "reasoning tokens" before writing visible output,
    which count against your token budget but never show up as content.
    `reasoning_effort="low"` keeps that spend down for what is
    fundamentally a templated content-generation task.
`_is_reasoning_model()` below is a name-pattern heuristic — if your
deployment name doesn't obviously contain "gpt-5" or match o1/o3/o4,
check this function if things behave unexpectedly.

If the response comes back with no visible content (all of
max_completion_tokens spent on hidden reasoning, nothing left to
write), that raises too, with a message telling you what to check —
it does not return an empty string and let the rest of the pipeline
quietly treat that as valid HTML.

Env vars (all required, no optional alternates):
    AZURE_OPENAI_API_KEY
    AZURE_OPENAI_ENDPOINT       e.g. https://<resource>.openai.azure.com
    AZURE_OPENAI_API_VERSION    e.g. 2025-01-01 (defaults to 2024-10-21 if unset)
    AZURE_OPENAI_DEPLOYMENT     e.g. gpt-5-mini (defaults to gpt-4o-mini if unset)
"""

from __future__ import annotations

import os
import re
from dotenv import load_dotenv
import openai
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

load_dotenv()


def _is_reasoning_model(deployment_name: str) -> bool:
    n = deployment_name.lower()
    if "gpt-5" in n:
        return True
    if re.match(r"^o[134](-mini|-pro)?$", n):
        return True
    return False


class LLMClient:
    def __init__(self):
        if not (os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT")):
            raise RuntimeError(
                "Missing Azure OpenAI credentials. Set AZURE_OPENAI_API_KEY and "
                "AZURE_OPENAI_ENDPOINT (and optionally AZURE_OPENAI_API_VERSION / "
                "AZURE_OPENAI_DEPLOYMENT) as environment variables. This project only "
                "supports Azure OpenAI — there is no fallback to another provider."
            )

        self.provider = "azure"
        self.last_usage = None  # populated after each complete() call; pipeline.py can log it

        endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
        if endpoint.endswith("/v1") or endpoint.endswith("/v1/"):
            from openai import OpenAI
            self._client = OpenAI(
                api_key=os.environ["AZURE_OPENAI_API_KEY"],
                base_url=endpoint,
                default_headers={"api-key": os.environ["AZURE_OPENAI_API_KEY"]}
            )
        else:
            from openai import AzureOpenAI
            self._client = AzureOpenAI(
                api_key=os.environ["AZURE_OPENAI_API_KEY"],
                azure_endpoint=endpoint,
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            )
        self._deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
        self._is_reasoning = _is_reasoning_model(self._deployment)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((
            openai.RateLimitError,
            openai.APIConnectionError,
            openai.InternalServerError,
        )),
        reraise=True
    )
    def complete(self, system: str, user: str, max_tokens: int = 4000, images: list[str] = None) -> str:
        if images:
            user_content = [{"type": "text", "text": user}]
            for b64 in images:
                user_content.append({"type": "image_url", "image_url": {"url": b64}})
        else:
            user_content = user

        kwargs = dict(
            model=self._deployment,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
        )
        if self._is_reasoning:
            # temperature and max_tokens are both rejected by reasoning models — see
            # module docstring. reasoning_effort="low" keeps hidden thinking-token spend
            # down for a templated generation task that doesn't need deep deliberation.
            kwargs["max_completion_tokens"] = max_tokens
            kwargs["reasoning_effort"] = "low"
        else:
            kwargs["max_tokens"] = max_tokens
            kwargs["temperature"] = 0.4

        # The tenacity decorator handles retries for transient errors.
        resp = self._client.chat.completions.create(**kwargs)

        content = resp.choices[0].message.content
        if not content:
            finish_reason = resp.choices[0].finish_reason
            raise RuntimeError(
                f"Model '{self._deployment}' returned empty content (finish_reason="
                f"{finish_reason!r}). If this is a reasoning model, it likely spent the "
                f"entire max_completion_tokens budget on hidden reasoning tokens with "
                f"nothing left for visible output — raise max_tokens or check "
                f"usage.completion_tokens_details.reasoning_tokens on the response."
            )

        usage = resp.usage
        usage_dict = {"input_tokens": usage.prompt_tokens, "output_tokens": usage.completion_tokens}
        cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", None)
        if cached:
            usage_dict["cache_read_input_tokens"] = cached
        reasoning = getattr(getattr(usage, "completion_tokens_details", None), "reasoning_tokens", None)
        if reasoning:
            usage_dict["reasoning_tokens"] = reasoning
        self.last_usage = usage_dict
        return content
