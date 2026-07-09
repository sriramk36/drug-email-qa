import os
from pathlib import Path
from typing import Any, Dict

from tenacity import retry, stop_after_attempt, wait_exponential

try:
    from openai import AzureOpenAI, OpenAI
except ModuleNotFoundError:  # pragma: no cover - exercised when dependency is unavailable
    AzureOpenAI = None
    OpenAI = None

try:
    from azure.identity import DefaultAzureCredential
except ModuleNotFoundError:  # pragma: no cover - exercised when dependency is unavailable
    DefaultAzureCredential = None

from config import settings
from knowledge.context import build_context


def _extract_response_text(response: Any) -> str:
    if hasattr(response, "output_text") and response.output_text:
        return response.output_text
    if hasattr(response, "output"):
        output = response.output
        if isinstance(output, str):
            return output
        if isinstance(output, list) and output:
            first = output[0]
            if hasattr(first, "content"):
                return first.content
            if isinstance(first, dict):
                return first.get("content") or first.get("text") or str(first)
        return str(output)
    if hasattr(response, "choices") and response.choices:
        first_choice = response.choices[0]
        if hasattr(first_choice, "message"):
            return first_choice.message.content
        if hasattr(first_choice, "text"):
            return first_choice.text
    return str(response)


def get_client_and_model():
    if settings.azure_openai_endpoint and settings.azure_openai_deployment:
        if OpenAI is None and AzureOpenAI is None:
            raise EnvironmentError(
                "The OpenAI SDK is not installed. Install the openai package before running this project."
            )

        if settings.is_azure_ai_services():
            if OpenAI is None:
                raise EnvironmentError(
                    "The openai package is required for Azure AI Services endpoint support."
                )
            if settings.azure_openai_api_key:
                client = OpenAI(base_url=settings.azure_openai_endpoint, api_key=settings.azure_openai_api_key)
            elif DefaultAzureCredential is not None:
                client = OpenAI(base_url=settings.azure_openai_endpoint, credential=DefaultAzureCredential())
            else:
                raise EnvironmentError(
                    "Azure AI Services auth requires AZURE_OPENAI_API_KEY or the azure-identity package "
                    "with DefaultAzureCredential available."
                )
            return client, settings.azure_openai_deployment

        if AzureOpenAI is None:
            raise EnvironmentError(
                "Azure OpenAI support requires the openai package with AzureOpenAI available."
            )
        if not settings.azure_openai_api_key:
            raise EnvironmentError(
                "AZURE_OPENAI_API_KEY is required for Azure OpenAI deployment support."
            )
        client = AzureOpenAI(
            api_key=settings.azure_openai_api_key,
            azure_endpoint=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_api_version,
        )
        return client, settings.azure_openai_deployment

    if OpenAI is not None and settings.openai_api_key:
        client = OpenAI(api_key=settings.openai_api_key)
        return client, "gpt-4o-mini"

    return None, None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def generate_email(campaign: Dict[str, Any], feedback: str | None = None) -> str:
    context = build_context(campaign)
    client, model = get_client_and_model()

    if client is None or model is None:
        raise EnvironmentError(
            "OpenAI/Azure client is not configured. "
            "Check that .env contains a valid AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, "
            "and AZURE_OPENAI_DEPLOYMENT, or OPENAI_API_KEY for OpenAI."
        )

    system_prompt = """You are a healthcare email writer for a drug awareness campaign.

Write a safe, compliant email using the provided context.

RULES:
- Do NOT make medical claims not provided
- Keep tone educational and supportive
- No exaggerated benefits
- Include subject, body, CTA
- Mention the drug name and encourage professional guidance"""

    user_prompt = f"CONTEXT:\n{context}\n"
    if feedback:
        user_prompt += f"\nFIX THESE ISSUES ONLY:\n{feedback}\n"

    if hasattr(client, "responses"):
        prompt = system_prompt + "\n\n" + user_prompt
        response = client.responses.create(model=model, input=prompt)
        return _extract_response_text(response)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
    )
    return _extract_response_text(response)
