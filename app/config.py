from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional

from .llm import LLMProvider


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_prefix": "MEMORY_", "extra": "ignore"}

    # Default LLM (fallback for all agents)
    llm_provider: LLMProvider = LLMProvider.DEEPSEEK

    # Per-agent LLM overrides
    critic_llm_provider: Optional[LLMProvider] = None
    researcher_llm_provider: Optional[LLMProvider] = None
    advocate_llm_provider: Optional[LLMProvider] = None
    sentiment_llm_provider: Optional[LLMProvider] = None
    macro_llm_provider: Optional[LLMProvider] = None

    # Per-agent LLM model overrides
    critic_llm_model: str = ""
    researcher_llm_model: str = ""
    advocate_llm_model: str = ""
    sentiment_llm_model: str = ""
    macro_llm_model: str = ""

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_base_url: str = ""

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"

    # AWS Bedrock
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"
    bedrock_model: str = "us.anthropic.claude-sonnet-4-20250514-v1:0"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"

    # Production risk controls
    min_hold_time: int = 300
    min_price_delta_pct: float = 0.1
    daily_loss_limit_pct: float = 2.0
    postmortem_min_loss_pct: float = 0.1
    short_enabled: bool = False

    # Infrastructure
    lance_db_path: str = "./data/lancedb"
    critic_port: int = 8000
    execution_engine_url: str = "http://127.0.0.1:9001"
    similarity_threshold: float = 0.15
    max_daily_postmortems: int = 20
    vector_dim: int = 6

    def agent_provider(self, agent: str) -> LLMProvider:
        """Get LLM provider for a specific agent, falling back to default."""
        overrides = {
            "critic": self.critic_llm_provider,
            "researcher": self.researcher_llm_provider,
            "advocate": self.advocate_llm_provider,
            "sentiment": self.sentiment_llm_provider,
            "macro": self.macro_llm_provider,
        }
        return overrides.get(agent) or self.llm_provider

    def agent_model(self, agent: str) -> str:
        """Get LLM model for a specific agent, empty string means use provider default."""
        overrides = {
            "critic": self.critic_llm_model,
            "researcher": self.researcher_llm_model,
            "advocate": self.advocate_llm_model,
            "sentiment": self.sentiment_llm_model,
            "macro": self.macro_llm_model,
        }
        return overrides.get(agent, "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
