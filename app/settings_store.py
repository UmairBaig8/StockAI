import json
import os
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SETTINGS_PATH = Path(os.getenv("SETTINGS_PATH", str(Path(__file__).parent.parent / "data" / "settings.json")))
SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)

DEFAULTS: dict[str, Any] = {
    "tickers": os.getenv("STRATEGY_TICKERS", "RELIANCE.NS,TATAPOWER.NS,HAL.NS,BEL.NS,SBIN.NS"),
    "max_positions": int(os.getenv("STRATEGY_MAX_POSITIONS", "3")),
    "position_size_pct": float(os.getenv("STRATEGY_POSITION_SIZE_PCT", "5")),
    "take_profit_pct": float(os.getenv("STRATEGY_TAKE_PROFIT_PCT", "2.0")),
    "stop_loss_pct": float(os.getenv("STRATEGY_STOP_LOSS_PCT", "3.0")),
    "signal_cooldown": int(os.getenv("STRATEGY_SIGNAL_COOLDOWN", "120")),
    "rsi_period": int(os.getenv("STRATEGY_RSI_PERIOD", "14")),
    "rsi_oversold": float(os.getenv("STRATEGY_RSI_OVERSOLD", "55")),
    "rsi_overbought": float(os.getenv("STRATEGY_RSI_OVERBOUGHT", "70")),
    "min_drop_pct": float(os.getenv("STRATEGY_MIN_DROP_PCT", "0.2")),
    "force_trade_sec": int(os.getenv("STRATEGY_FORCE_TRADE_SEC", "300")),
    "initial_capital": float(os.getenv("STRATEGY_INITIAL_CAPITAL", "100000")),
    "llm_provider": os.getenv("MEMORY_LLM_PROVIDER", "deepseek"),
    "llm_model": os.getenv("MEMORY_DEEPSEEK_MODEL", "deepseek-chat"),
    # Per-agent LLM overrides
    "llm_critic_provider": os.getenv("MEMORY_CRITIC_LLM_PROVIDER", ""),
    "llm_critic_model": os.getenv("MEMORY_CRITIC_LLM_MODEL", ""),
    "llm_researcher_provider": os.getenv("MEMORY_RESEARCHER_LLM_PROVIDER", ""),
    "llm_researcher_model": os.getenv("MEMORY_RESEARCHER_LLM_MODEL", ""),
    "llm_advocate_provider": os.getenv("MEMORY_ADVOCATE_LLM_PROVIDER", ""),
    "llm_advocate_model": os.getenv("MEMORY_ADVOCATE_LLM_MODEL", ""),
    "llm_sentiment_provider": os.getenv("MEMORY_SENTIMENT_LLM_PROVIDER", ""),
    "llm_sentiment_model": os.getenv("MEMORY_SENTIMENT_LLM_MODEL", ""),
    "llm_macro_provider": os.getenv("MEMORY_MACRO_LLM_PROVIDER", ""),
    "llm_macro_model": os.getenv("MEMORY_MACRO_LLM_MODEL", ""),
}

_callbacks: list = []


def load() -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    if SETTINGS_PATH.exists():
        try:
            saved = json.loads(SETTINGS_PATH.read_text())
            cfg.update(saved)
        except Exception as e:
            logger.error(f"Failed to load settings: {e}")
    return cfg


def save(data: dict[str, Any]) -> dict[str, Any]:
    safe = {}
    for k, v in data.items():
        if k in DEFAULTS:
            dtype = type(DEFAULTS[k])
            try:
                if dtype == int:
                    safe[k] = int(v)
                elif dtype == float:
                    safe[k] = float(v)
                else:
                    safe[k] = str(v)
            except (ValueError, TypeError):
                logger.warning(f"Invalid value for {k}: {v}")

    SETTINGS_PATH.write_text(json.dumps(safe, indent=2))
    logger.info(f"Settings saved: {list(safe.keys())}")

    for cb in _callbacks:
        try:
            cb(safe)
        except Exception as e:
            logger.error(f"Settings callback error: {e}")

    return load()


def on_change(callback):
    _callbacks.append(callback)


def current() -> dict[str, Any]:
    return load()
