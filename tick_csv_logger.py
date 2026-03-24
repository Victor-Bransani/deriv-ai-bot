"""
Gravação em CSV de ticks (WebSocket Deriv) e de um snapshot por ciclo de análise (features p/ ML).
"""
from __future__ import annotations

import asyncio
import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Colunas estáveis para datasets de treino
TICK_CSV_FIELDS: List[str] = [
    "ts_utc_iso",
    "epoch",
    "symbol",
    "quote",
    "bid",
    "ask",
    "tick_id",
    "pip_size",
    "raw_tick_json",
]

CYCLE_CSV_FIELDS: List[str] = [
    "ts_utc_iso",
    "symbol_ui",
    "symbol_deriv",
    "running",
    "balance",
    "phase",
    "signal",
    "confidence",
    "reason",
    "m15_tide",
    "m5_epoch",
    "m5_open",
    "m5_high",
    "m5_low",
    "m5_close",
    "m15_epoch",
    "m15_close",
    "rsi_m5",
    "macd_m5_line",
    "macd_m5_signal",
    "macd_cross",
    "macd_favors",
    "rsi_ok",
    "bb_upper",
    "bb_lower",
    "bb_breakout_up",
    "bb_breakout_down",
    "obi",
    "alert_side",
    "trade_blocked_reason",
]


def _utc_iso_from_epoch(epoch: Any) -> str:
    try:
        ep = float(epoch)
        if ep > 1e12:
            ep = ep / 1000.0
        return datetime.fromtimestamp(ep, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return datetime.now(timezone.utc).isoformat()


class TickCsvWriter:
    """Um ficheiro por dia UTC: ticks_YYYY-MM-DD.csv"""

    def __init__(self, data_dir: Path) -> None:
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    def _path(self) -> Path:
        d = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._dir / f"ticks_{d}.csv"

    async def append_ws_tick_message(self, msg: Dict[str, Any]) -> None:
        tick = msg.get("tick")
        if not isinstance(tick, dict):
            return
        epoch = tick.get("epoch")
        row = {
            "ts_utc_iso": _utc_iso_from_epoch(epoch),
            "epoch": epoch,
            "symbol": tick.get("symbol", ""),
            "quote": tick.get("quote", ""),
            "bid": tick.get("bid", ""),
            "ask": tick.get("ask", ""),
            "tick_id": tick.get("id", ""),
            "pip_size": tick.get("pip_size", ""),
            "raw_tick_json": json.dumps(tick, separators=(",", ":"), default=str),
        }
        async with self._lock:
            path = self._path()
            new_file = not path.exists()
            with path.open("a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=TICK_CSV_FIELDS, extrasaction="ignore")
                if new_file:
                    w.writeheader()
                w.writerow(row)
                f.flush()


class CycleCsvWriter:
    """Um snapshot por ciclo de análise: cycles_YYYY-MM-DD.csv"""

    def __init__(self, data_dir: Path) -> None:
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    def _path(self) -> Path:
        d = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._dir / f"cycles_{d}.csv"

    async def append_cycle(self, row: Dict[str, Any]) -> None:
        out = {k: row.get(k, "") for k in CYCLE_CSV_FIELDS}
        if "ts_utc_iso" not in out or not out["ts_utc_iso"]:
            out["ts_utc_iso"] = datetime.now(timezone.utc).isoformat()
        async with self._lock:
            path = self._path()
            new_file = not path.exists()
            with path.open("a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=CYCLE_CSV_FIELDS, extrasaction="ignore")
                if new_file:
                    w.writeheader()
                w.writerow(out)
                f.flush()
