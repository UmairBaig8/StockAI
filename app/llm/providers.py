import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Optional

from . import LLMProvider

logger = logging.getLogger(__name__)


class LLMAdapter(ABC):
    provider: LLMProvider

    @abstractmethod
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> str: ...

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        t = text.strip()
        if t.startswith("```"):
            lines = t.split("\n")
            t = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        return t

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> dict:
        text = self.generate(system_prompt, user_prompt, temperature, max_tokens)
        text = self._strip_code_fences(text)
        return json.loads(text)


class GeminiAdapter(LLMAdapter):
    provider = LLMProvider.GEMINI

    def __init__(self, api_key: str, model: str = "gemini-1.5-pro"):
        from google import genai

        self.client = genai.Client(api_key=api_key)
        self.model = model

    def generate(
        self, system_prompt: str, user_prompt: str, temperature: float = 0.3, max_tokens: int = 1024
    ) -> str:
        response = self.client.models.generate_content(
            model=self.model,
            contents=user_prompt,
            config={
                "system_instruction": system_prompt,
                "temperature": temperature,
                "max_output_tokens": max_tokens,
            },
        )
        return response.text


class OpenAIAdapter(LLMAdapter):
    provider = LLMProvider.OPENAI

    def __init__(self, api_key: str, model: str = "gpt-4o", base_url: Optional[str] = None):
        from openai import OpenAI

        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)
        self.model = model

    def generate(
        self, system_prompt: str, user_prompt: str, temperature: float = 0.3, max_tokens: int = 1024
    ) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""


class AnthropicAdapter(LLMAdapter):
    provider = LLMProvider.ANTHROPIC

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        from anthropic import Anthropic

        self.client = Anthropic(api_key=api_key)
        self.model = model

    def generate(
        self, system_prompt: str, user_prompt: str, temperature: float = 0.3, max_tokens: int = 1024
    ) -> str:
        response = self.client.messages.create(
            model=self.model,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = response.content[0]
        return content.text if hasattr(content, "text") else str(content)


class DeepSeekAdapter(LLMAdapter):
    provider = LLMProvider.DEEPSEEK

    def __init__(self, api_key: str, model: str = "deepseek-chat"):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        self.model = model

    def generate(
        self, system_prompt: str, user_prompt: str, temperature: float = 0.3, max_tokens: int = 1024
    ) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""


class BedrockAdapter(LLMAdapter):
    provider = LLMProvider.BEDROCK

    def __init__(
        self,
        aws_access_key: str,
        aws_secret_key: str,
        region: str = "us-east-1",
        model: str = "us.anthropic.claude-sonnet-4-20250514-v1:0",
    ):
        import boto3

        self.client = boto3.client(
            "bedrock-runtime",
            region_name=region,
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
        )
        self.model = model

    def generate(
        self, system_prompt: str, user_prompt: str, temperature: float = 0.3, max_tokens: int = 1024
    ) -> str:
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        })
        response = self.client.invoke_model(modelId=self.model, body=body)
        result = json.loads(response["body"].read())
        content = result.get("content", [{}])
        return content[0].get("text", "") if content else ""


class OllamaAdapter(LLMAdapter):
    provider = LLMProvider.OLLAMA

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3.1"):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def generate(
        self, system_prompt: str, user_prompt: str, temperature: float = 0.3, max_tokens: int = 1024
    ) -> str:
        import httpx

        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        with httpx.Client(timeout=120) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data["message"]["content"]


def create_llm(settings) -> LLMAdapter:
    return create_llm_for_agent(settings, "default")


def create_llm_for_agent(settings, agent: str) -> LLMAdapter:
    provider = settings.agent_provider(agent)

    if provider == LLMProvider.GEMINI:
        return GeminiAdapter(api_key=settings.gemini_api_key, model=settings.gemini_model)

    if provider == LLMProvider.OPENAI:
        return OpenAIAdapter(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            base_url=settings.openai_base_url or None,
        )

    if provider == LLMProvider.ANTHROPIC:
        return AnthropicAdapter(api_key=settings.anthropic_api_key, model=settings.anthropic_model)

    if provider == LLMProvider.DEEPSEEK:
        return DeepSeekAdapter(api_key=settings.deepseek_api_key, model=settings.deepseek_model)

    if provider == LLMProvider.BEDROCK:
        return BedrockAdapter(
            aws_access_key=settings.aws_access_key_id,
            aws_secret_key=settings.aws_secret_access_key,
            region=settings.aws_region,
            model=settings.bedrock_model,
        )

    if provider == LLMProvider.OLLAMA:
        return OllamaAdapter(base_url=settings.ollama_base_url, model=settings.ollama_model)

    raise ValueError(f"Unknown LLM provider: {provider}")


# ── LLM Health Check ──

ALL_PROVIDERS = ["openai", "deepseek", "gemini", "anthropic", "bedrock", "ollama"]
PROVIDER_LABELS = {"openai":"OpenAI","deepseek":"DeepSeek","gemini":"Gemini","anthropic":"Anthropic","bedrock":"AWS Bedrock","ollama":"Ollama"}
PROVIDER_ENV_KEYS = {"openai":"MEMORY_OPENAI_API_KEY","deepseek":"MEMORY_DEEPSEEK_API_KEY","gemini":"MEMORY_GEMINI_API_KEY","anthropic":"MEMORY_ANTHROPIC_API_KEY","bedrock":"MEMORY_AWS_ACCESS_KEY_ID","ollama":"MEMORY_OLLAMA_BASE_URL"}
PROVIDER_DEFAULT_MODEL = {"openai":"gpt-4o-mini","deepseek":"deepseek-chat","gemini":"gemini-2.5-flash","anthropic":"claude-sonnet-4-20250514","bedrock":"us.anthropic.claude-sonnet-4-20250514-v1:0","ollama":"llama3.1"}


def check_llm_health() -> dict:
    results = {}
    for provider in ALL_PROVIDERS:
        key = os.getenv(PROVIDER_ENV_KEYS.get(provider, ""), "")
        configured = bool(key and key.strip() and len(key) > 10)
        results[provider] = {
            "label": PROVIDER_LABELS.get(provider, provider),
            "configured": configured,
            "model": os.getenv(f"MEMORY_{provider.upper()}_MODEL", "") or PROVIDER_DEFAULT_MODEL.get(provider, ""),
            "default": os.getenv("MEMORY_LLM_PROVIDER", "deepseek") == provider,
        }
    return results


def get_available_providers() -> list[str]:
    return [p for p, h in check_llm_health().items() if h["configured"]]


def get_active_provider() -> str:
    return os.getenv("MEMORY_LLM_PROVIDER", "deepseek")
