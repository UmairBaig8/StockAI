from enum import Enum


class LLMProvider(str, Enum):
    GEMINI = "gemini"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"
    BEDROCK = "bedrock"
    OLLAMA = "ollama"
