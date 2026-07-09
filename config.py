import os
from typing import Optional
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    azure_openai_endpoint: Optional[str] = Field(default=None, validation_alias='AZURE_OPENAI_ENDPOINT')
    azure_openai_deployment: Optional[str] = Field(default=None, validation_alias='AZURE_OPENAI_DEPLOYMENT')
    azure_openai_api_key: Optional[str] = Field(default=None, validation_alias='AZURE_OPENAI_API_KEY')
    azure_openai_api_version: str = Field(default="2024-02-15-preview", validation_alias='AZURE_OPENAI_API_VERSION')
    openai_api_key: Optional[str] = Field(default=None, validation_alias='OPENAI_API_KEY')

    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8", 
        extra="ignore"
    )

    @field_validator('azure_openai_endpoint')
    @classmethod
    def validate_azure_endpoint(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return v
            
        endpoint = v.rstrip("/")
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError(f"AZURE_OPENAI_ENDPOINT must be a valid URL with http or https: {endpoint}")
        if not parsed.hostname:
            raise ValueError(f"AZURE_OPENAI_ENDPOINT must include a valid host: {endpoint}")

        host = parsed.hostname.lower()
        if host.endswith(".openai.azure.com"):
            if parsed.path and parsed.path not in {"", "/"}:
                raise ValueError(
                    "AZURE_OPENAI_ENDPOINT must be the base resource host only, "
                    f"not a project or API path. Current value: {endpoint}"
                )
            return endpoint

        if host.endswith(".services.ai.azure.com"):
            if not parsed.path.startswith("/openai"):
                raise ValueError(
                    "AZURE_OPENAI_ENDPOINT for Azure AI Services must include /openai or /openai/v1. "
                    f"Current value: {endpoint}"
                )
            return endpoint

        raise ValueError(
            "AZURE_OPENAI_ENDPOINT must point to an Azure OpenAI or Azure AI Services host. "
            f"Current value: {endpoint}"
        )

    def is_azure_ai_services(self) -> bool:
        if not self.azure_openai_endpoint:
            return False
        parsed = urlparse(self.azure_openai_endpoint)
        return bool(parsed.hostname and parsed.hostname.lower().endswith(".services.ai.azure.com"))

settings = Settings()
