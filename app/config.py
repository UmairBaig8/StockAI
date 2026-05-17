from pydantic_settings import BaseSettings
from functools import lru_cache

from .llm import LLMProvider


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_prefix": "MEMORY_", "extra": "ignore"}

    llm_provider: LLMProvider = LLMProvider.DEEPSEEK

    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-pro"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_base_url: str = ""

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"

    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"
    bedrock_model: str = "us.anthropic.claude-sonnet-4-20250514-v1:0"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"

    lance_db_path: str = "./data/lancedb"
    critic_port: int = 8000
    execution_engine_url: str = "http://127.0.0.1:9001"
    similarity_threshold: float = 0.15
    max_daily_postmortems: int = 20
    vector_dim: int = 6


@lru_cache
def get_settings() -> Settings:
    return Settings()
