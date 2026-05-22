import json
import logging
import os
import time
from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from . import LLMProvider

logger = logging.getLogger(__name__)

# Circular buffer for LLM traces (last 200 calls)
_trace_buffer: deque[dict] = deque(maxlen=200)


def _record_trace(agent: str, provider: str, model: str, prompt_chars: int,
                   response_chars: int, latency_ms: float, success: bool, error: str = "",
                   prompt_text: str = "", response_text: str = ""):
    trace = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": agent,
        "provider": provider,
        "model": model,
        "prompt_tokens_est": max(1, prompt_chars // 4),
        "response_tokens_est": max(1, response_chars // 4),
        "latency_ms": round(latency_ms, 1),
        "success": success,
        "error": error[:200] if error else "",
        "prompt": prompt_text[:1000] if prompt_text else "",
        "response": response_text[:2000] if response_text else "",
    }
    _trace_buffer.append(trace)
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_persist_trace(trace))
        else:
            asyncio.run(_persist_trace(trace))
    except RuntimeError:
        import asyncio as _asyncio
        _asyncio.run(_persist_trace(trace))


async def _persist_trace(trace: dict):
    """Persist trace to PostgreSQL."""
    try:
        from .db import save_llm_trace
        await save_llm_trace(trace)
    except Exception as e:
        logger.error(f"Failed to persist trace: {e}")


def get_traces(limit: int = 100) -> list[dict]:
    items = list(_trace_buffer)
    return items[-limit:]


async def get_traces_with_db(limit: int = 100) -> list[dict]:
    """Get traces from in-memory buffer, falling back to PostgreSQL for older entries."""
    items = list(_trace_buffer)
    if len(items) >= limit:
        return items[-limit:]
    # Need more from DB
    try:
        from .db import load_llm_traces
        db_traces = await load_llm_traces(limit - len(items))
        # Deduplicate: skip any DB traces already in memory buffer
        mem_timestamps = {t["timestamp"] for t in items}
        deduped = [t for t in db_traces if t["timestamp"] not in mem_timestamps]
        return deduped + items
    except Exception:
        return items[-limit:] if items else []


class LLMAdapter(ABC):
    provider: LLMProvider
    agent_name: str = "unknown"
    model_name: str = "unknown"

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

    @staticmethod
    def _strip_reasoning(text: str) -> str:
        """Strip deepseek-reasoner  response wrappers."""
        import re
        t = text.strip()
        t = re.sub(r'<\s*think\s*>.*?<\s*/\s*think\s*>', '', t, flags=re.DOTALL)
        t = re.sub(r'<\s*reasoning\s*>.*?<\s*/\s*reasoning\s*>', '', t, flags=re.DOTALL)
        return t.strip()

    @staticmethod
    def _try_recover_json(text: str) -> str:
        """Attempt to recover truncated/broken JSON."""
        t = text.strip()
        if not t:
            return None
        if t[0] not in ('{', '['):
            return None
        # close unterminated strings
        in_str = False
        escaped = False
        result = []
        for ch in t:
            result.append(ch)
            if escaped:
                escaped = False
                continue
            if ch == '\\':
                escaped = True
                continue
            if ch == '"':
                in_str = not in_str
        reconstructed = ''.join(result)
        # balance braces and brackets
        brace_depth = 0
        bracket_depth = 0
        for ch in reconstructed:
            if ch == '{':
                brace_depth += 1
            elif ch == '}':
                brace_depth -= 1
            elif ch == '[':
                bracket_depth += 1
            elif ch == ']':
                bracket_depth -= 1
        if in_str:
            reconstructed += '"'
        for _ in range(max(brace_depth, 0)):
            reconstructed += '}'
        for _ in range(max(bracket_depth, 0)):
            reconstructed += ']'
        return reconstructed

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        max_retries: int = 2,
    ) -> dict:
        import re

        prompt_chars = len(system_prompt) + len(user_prompt)
        prompt_full = f"[SYSTEM]\n{system_prompt[:800]}\n\n[USER]\n{user_prompt[:800]}"
        last_error = ""

        for attempt in range(max_retries + 1):
            t0 = time.monotonic()
            try:
                full_user = user_prompt + ("\n\nRespond with valid JSON only. No markdown, no explanation." if attempt == 0 else "")
                text = self.generate(
                    system_prompt,
                    full_user,
                    temperature=max(0.1, temperature - 0.1 * attempt),
                    max_tokens=max_tokens,
                )
                elapsed = (time.monotonic() - t0) * 1000

                if not text or not text.strip():
                    last_error = "empty response from LLM"
                    continue

                raw_text = text
                text = self._strip_reasoning(text)
                text = self._strip_code_fences(text).strip()

                if not text:
                    last_error = "empty after stripping reasoning/code fences"
                    continue

                try:
                    result = json.loads(text)
                except json.JSONDecodeError:
                    recovered = self._try_recover_json(text)
                    if recovered and recovered != text:
                        try:
                            result = json.loads(recovered)
                        except json.JSONDecodeError as e2:
                            last_error = str(e2)
                            continue
                    else:
                        last_error = str(json.JSONDecodeError("", text[:80], 0))
                        continue

                _record_trace(self.agent_name, self.provider.value, self.model,
                             prompt_chars, len(text), elapsed, True,
                             prompt_text=prompt_full, response_text=raw_text[:2000])
                return result

            except Exception as e:
                elapsed = (time.monotonic() - t0) * 1000
                last_error = str(e)

        elapsed = (time.monotonic() - t0) * 1000 if 't0' in dir() else 0
        _record_trace(self.agent_name, self.provider.value, self.model,
                     prompt_chars, 0, elapsed, False, last_error,
                     prompt_text=prompt_full, response_text="")
        raise ValueError(f"LLM failed after {max_retries + 1} attempts: {last_error}")


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
        msg = response.choices[0].message
        content = msg.content or ""
        if not content and hasattr(msg, 'reasoning_content'):
            content = msg.reasoning_content or ""
        return content


class BedrockAdapter(LLMAdapter):
    provider = LLMProvider.BEDROCK

    # Map model prefixes to body formats
    ANTHROPIC_PREFIXES = ("anthropic.", "claude")
    DEEPSEEK_PREFIXES = ("deepseek.",)
    META_PREFIXES = ("meta.", "llama")
    GOOGLE_PREFIXES = ("google.", "gemma", "gemini")
    QWEN_PREFIXES = ("qwen.",)
    NOVA_PREFIXES = ("amazon.nova",)
    MISTRAL_PREFIXES = ("mistral.",)

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

    def _is_provider(self, prefixes: tuple) -> bool:
        return any(p in self.model.lower() for p in prefixes)

    def generate(
        self, system_prompt: str, user_prompt: str, temperature: float = 0.3, max_tokens: int = 1024
    ) -> str:
        if self._is_provider(self.ANTHROPIC_PREFIXES):
            return self._generate_anthropic(system_prompt, user_prompt, temperature, max_tokens)
        return self._generate_converse(system_prompt, user_prompt, temperature, max_tokens)

    def _generate_anthropic(self, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int) -> str:
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

    def _generate_converse(self, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int) -> str:
        """Use Bedrock Converse API for non-Anthropic models (DeepSeek, Llama, etc.)"""
        messages = [{"role": "user", "content": [{"text": user_prompt}]}]
        sys_doc = [{"text": system_prompt}] if system_prompt else []
        kwargs = {"modelId": self.model, "messages": messages}
        if sys_doc:
            kwargs["system"] = sys_doc
        kwargs["inferenceConfig"] = {"temperature": temperature, "maxTokens": max_tokens}
        response = self.client.converse(**kwargs)
        output = response.get("output", {}).get("message", {}).get("content", [{}])
        return output[0].get("text", "") if output else ""


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
    model_override = settings.agent_model(agent) if hasattr(settings, 'agent_model') else ""

    if provider == LLMProvider.GEMINI:
        llm = GeminiAdapter(api_key=settings.gemini_api_key, model=model_override or settings.gemini_model)
    elif provider == LLMProvider.OPENAI:
        llm = OpenAIAdapter(
            api_key=settings.openai_api_key,
            model=model_override or settings.openai_model,
            base_url=settings.openai_base_url or None,
        )
    elif provider == LLMProvider.ANTHROPIC:
        llm = AnthropicAdapter(api_key=settings.anthropic_api_key, model=model_override or settings.anthropic_model)
    elif provider == LLMProvider.DEEPSEEK:
        llm = DeepSeekAdapter(api_key=settings.deepseek_api_key, model=model_override or settings.deepseek_model)
    elif provider == LLMProvider.BEDROCK:
        llm = BedrockAdapter(
            aws_access_key=settings.aws_access_key_id,
            aws_secret_key=settings.aws_secret_access_key,
            region=settings.aws_region,
            model=model_override or settings.bedrock_model,
        )
    elif provider == LLMProvider.OLLAMA:
        llm = OllamaAdapter(base_url=settings.ollama_base_url, model=model_override or settings.ollama_model)
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")

    llm.agent_name = agent
    return llm


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
