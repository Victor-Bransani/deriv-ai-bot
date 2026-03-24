"""
Overrides persistidos (Telegram). Valores ausentes usam o .env / config.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import config

logger = logging.getLogger(__name__)

_PATH = Path(__file__).resolve().parent / "user_settings.json"
_store: dict[str, Any] = {}


def load() -> None:
    global _store
    if not _PATH.exists():
        _store = {}
        return
    try:
        raw = _PATH.read_text(encoding="utf-8")
        _store = json.loads(raw) if raw.strip() else {}
        if not isinstance(_store, dict):
            _store = {}
    except Exception as e:
        logger.warning("user_settings: falha ao ler %s: %s", _PATH, e)
        _store = {}


def save() -> None:
    try:
        _PATH.write_text(
            json.dumps(_store, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("user_settings: falha ao gravar %s: %s", _PATH, e)


def _get(key: str) -> Any:
    return _store.get(key)


def effective_bool(key: str, default: bool) -> bool:
    v = _get(key)
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def effective_float(key: str, default: float) -> float:
    v = _get(key)
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def effective_int(key: str, default: int) -> int:
    v = _get(key)
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def set_value(key: str, value: Any) -> None:
    _store[key] = value
    save()


def clear_kelly_keys() -> None:
    for k in list(_store.keys()):
        if k.startswith("kelly_") or k == "min_stake":
            del _store[k]
    save()


def has_any_kelly_override() -> bool:
    return any(
        k.startswith("kelly_") or k == "min_stake" for k in _store.keys()
    )


def clear_bank_keys() -> None:
    for k in ("tp_daily_pct", "sl_daily_pct"):
        _store.pop(k, None)
    save()


def has_any_bank_override() -> bool:
    return "tp_daily_pct" in _store or "sl_daily_pct" in _store


def bank_snapshot() -> dict:
    return {
        "tp_daily_pct": effective_float("tp_daily_pct", config.TP_DAILY_PCT),
        "sl_daily_pct": effective_float("sl_daily_pct", config.SL_DAILY_PCT),
    }


def kelly_snapshot() -> dict:
    return {
        "enabled": effective_bool("kelly_enabled", config.KELLY_ENABLED),
        "fraction": effective_float("kelly_fraction", config.KELLY_FRACTION),
        "window": effective_int("kelly_window", config.KELLY_WINDOW),
        "min_trades": effective_int("kelly_min_trades", config.KELLY_MIN_TRADES),
        "default_payoff": effective_float(
            "kelly_default_win_payoff", config.KELLY_DEFAULT_WIN_PAYOFF
        ),
        "use_wilson": effective_bool("kelly_use_wilson", config.KELLY_USE_WILSON),
        "max_bankroll_fraction": effective_float(
            "kelly_max_bankroll_fraction", config.KELLY_MAX_BANKROLL_FRACTION
        ),
        "cap_full": effective_float("kelly_cap_full_fraction", config.KELLY_CAP_FULL_FRACTION),
        "dd_soft": effective_float("kelly_dd_soft_start", config.KELLY_DD_SOFT_START),
        "dd_min_scale": effective_float("kelly_dd_min_scale", config.KELLY_DD_MIN_SCALE),
        "min_stake": effective_float("min_stake", config.MIN_STAKE),
    }
