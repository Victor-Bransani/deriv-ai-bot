import logging
from typing import Any, Dict, List, Literal, Optional

import pandas as pd
import ta

import config
from order_book import OrderBookAnalyzer

logger = logging.getLogger(__name__)

MIN_M15 = 40
MIN_M5 = 35


def _ohlc_df(candles: List[Dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(candles)
    df.columns = ["epoch", "open", "high", "low", "close"]
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col])
    n0 = len(df)
    df.dropna(inplace=True)
    if len(df) < n0:
        logger.warning(
            "ai_engine: %s linha(s) removida(s) após OHLC inválidos",
            n0 - len(df),
        )
    return df


def _empty_diagnostics() -> Dict[str, Any]:
    return {
        "m15_tide": "",
        "m5_epoch": "",
        "m5_open": "",
        "m5_high": "",
        "m5_low": "",
        "m5_close": "",
        "m15_epoch": "",
        "m15_close": "",
        "rsi_m5": "",
        "macd_m5_line": "",
        "macd_m5_signal": "",
        "macd_cross": "",
        "macd_favors": "",
        "rsi_ok": "",
        "bb_upper": "",
        "bb_lower": "",
        "bb_breakout_up": "",
        "bb_breakout_down": "",
        "obi": "",
        "alert_side": "",
        "latest_tick_used": "",
    }


class AIEngine:
    """
    Sniper quantitativo em 3 fases: maré M15 → alerta M5 (MACD+RSI) → rompimento BB M5 + OBI.
    """

    def __init__(self) -> None:
        self.ob = OrderBookAnalyzer(window=100)
        self._alert_side: Optional[Literal["MULTUP", "MULTDOWN"]] = None

    def _m15_tide(self, df: pd.DataFrame) -> Optional[Literal["UP", "DOWN"]]:
        ema20 = ta.trend.EMAIndicator(df["close"], window=20).ema_indicator()
        macd = ta.trend.MACD(df["close"])
        mline = macd.macd()
        sig = macd.macd_signal()
        close = float(df["close"].iloc[-1])
        em = float(ema20.iloc[-1])
        mv = float(mline.iloc[-1])
        sv = float(sig.iloc[-1])
        if mv > sv and close > em:
            return "UP"
        if mv < sv and close < em:
            return "DOWN"
        return None

    def _m5_macd_cross(
        self, df: pd.DataFrame, favor: Literal["UP", "DOWN"]
    ) -> bool:
        macd = ta.trend.MACD(df["close"])
        mline = macd.macd()
        sig = macd.macd_signal()
        mp, sp = float(mline.iloc[-2]), float(sig.iloc[-2])
        mn, sn = float(mline.iloc[-1]), float(sig.iloc[-1])
        if favor == "UP":
            return mp <= sp and mn > sn
        return mp >= sp and mn < sn

    def _m5_rsi_ok(self, rsi_val: float, favor: Literal["UP", "DOWN"]) -> bool:
        if favor == "UP":
            return 48.0 <= rsi_val <= 60.0
        return 40.0 <= rsi_val <= 52.0

    def _m5_bb_breakout(
        self, df: pd.DataFrame, side: Literal["MULTUP", "MULTDOWN"]
    ) -> bool:
        bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2.0)
        upper = float(bb.bollinger_hband().iloc[-1])
        lower = float(bb.bollinger_lband().iloc[-1])
        close = float(df["close"].iloc[-1])
        if side == "MULTUP":
            return close > upper
        return close < lower

    def _fill_ohlc_diag(self, diag: Dict[str, Any], df15: pd.DataFrame, df5: pd.DataFrame) -> None:
        r5 = df5.iloc[-1]
        r15 = df15.iloc[-1]
        diag["m5_epoch"] = int(r5["epoch"])
        diag["m5_open"] = float(r5["open"])
        diag["m5_high"] = float(r5["high"])
        diag["m5_low"] = float(r5["low"])
        diag["m5_close"] = float(r5["close"])
        diag["m15_epoch"] = int(r15["epoch"])
        diag["m15_close"] = float(r15["close"])

    def analyze(
        self,
        candles_m15: List[Dict[str, Any]],
        candles_m5: List[Dict[str, Any]],
        latest_tick: float,
    ) -> Dict[str, Any]:
        diag = _empty_diagnostics()
        diag["latest_tick_used"] = float(latest_tick)

        wait = {
            "signal": "WAIT",
            "confidence": 0.0,
            "mode": "SNIPER",
            "reason": "",
            "phase": "",
            "diagnostics": diag,
        }

        if len(candles_m15) < MIN_M15 or len(candles_m5) < MIN_M5:
            msg = "Carregando velas M15/M5"
            logger.info("[Sniper] Aguardando M15 — %s", msg)
            return {**wait, "reason": msg, "phase": "load"}

        df15 = _ohlc_df(candles_m15)
        df5 = _ohlc_df(candles_m5)
        if len(df15) < MIN_M15 or len(df5) < MIN_M5:
            msg = "OHLC insuficiente após limpeza"
            logger.info("[Sniper] Aguardando M15 — %s", msg)
            return {**wait, "reason": msg, "phase": "load"}

        self._fill_ohlc_diag(diag, df15, df5)
        self.ob.add_tick(float(latest_tick))
        obi = float(self.ob.get_obi())
        diag["obi"] = obi

        bb = ta.volatility.BollingerBands(df5["close"], window=20, window_dev=2.0)
        diag["bb_upper"] = float(bb.bollinger_hband().iloc[-1])
        diag["bb_lower"] = float(bb.bollinger_lband().iloc[-1])
        c5 = float(df5["close"].iloc[-1])
        diag["bb_breakout_up"] = c5 > diag["bb_upper"]
        diag["bb_breakout_down"] = c5 < diag["bb_lower"]

        rsi5 = ta.momentum.RSIIndicator(df5["close"], window=14).rsi()
        rsi_now = float(rsi5.iloc[-1])
        diag["rsi_m5"] = rsi_now

        macd5 = ta.trend.MACD(df5["close"])
        m5_line = macd5.macd()
        m5_sig = macd5.macd_signal()
        mn = float(m5_line.iloc[-1])
        sn = float(m5_sig.iloc[-1])
        diag["macd_m5_line"] = mn
        diag["macd_m5_signal"] = sn

        tide = self._m15_tide(df15)
        diag["m15_tide"] = tide if tide else ""

        if tide is None:
            self._alert_side = None
            msg = "maré M15 indefinida (MACD + EMA20)"
            logger.info("[Sniper] Fase 1 — Aguardando M15 (%s)", msg)
            return {**wait, "reason": msg, "phase": "fase1", "diagnostics": diag}

        tide_msg = "maré alta M15" if tide == "UP" else "maré baixa M15"
        logger.info("[Sniper] Fase 1 — OK (%s); analisando M5", tide_msg)

        favor: Literal["UP", "DOWN"] = tide
        side: Literal["MULTUP", "MULTDOWN"] = "MULTUP" if tide == "UP" else "MULTDOWN"

        macd_favors = (mn > sn) if favor == "UP" else (mn < sn)
        cross = self._m5_macd_cross(df5, favor)
        rsi_ok = self._m5_rsi_ok(rsi_now, favor)
        diag["macd_favors"] = macd_favors
        diag["macd_cross"] = cross
        diag["rsi_ok"] = rsi_ok

        if self._alert_side is not None and self._alert_side != side:
            self._alert_side = None

        if self._alert_side is None:
            if not cross or not rsi_ok:
                msg = "M5 sem cruzamento MACD alinhado ou RSI fora da zona"
                logger.info(
                    "[Sniper] Fase 2 — aguardando alerta (%s; RSI=%.2f)",
                    msg,
                    rsi_now,
                )
                return {**wait, "reason": msg, "phase": "fase2_wait", "diagnostics": diag}
            self._alert_side = side
            logger.info(
                "[Sniper] Fase 2 — Alerta armado %s (cruzamento MACD + RSI=%.2f)",
                side,
                rsi_now,
            )
        else:
            if not rsi_ok or not macd_favors:
                self._alert_side = None
                logger.info(
                    "[Sniper] Fase 2 — alerta cancelado (RSI=%.2f ou MACD desalinhado)",
                    rsi_now,
                )
                return {
                    **wait,
                    "reason": "Alerta invalidado (RSI ou MACD M5)",
                    "phase": "fase2_drop",
                    "diagnostics": diag,
                }
            logger.info(
                "[Sniper] Fase 2 — Alerta armado %s (mantido; RSI=%.2f)",
                self._alert_side,
                rsi_now,
            )

        side = self._alert_side
        assert side is not None
        diag["alert_side"] = side

        if not self._m5_bb_breakout(df5, side):
            logger.info(
                "[Sniper] Fase 3 — em alerta; aguardando rompimento Bollinger (M5)"
            )
            return {
                **wait,
                "reason": "Alerta ativo — sem rompimento BB ainda",
                "phase": "fase3_wait_bb",
                "diagnostics": diag,
            }

        if side == "MULTUP":
            if obi <= 0.0:
                logger.info(
                    "[Sniper] Fase 3 — Rompimento detectado mas OBI=%.3f não confirma MULTUP",
                    obi,
                )
                return {
                    **wait,
                    "reason": "Rompimento BB sem confirmação OBI (>0)",
                    "phase": "fase3_obi_block",
                    "diagnostics": diag,
                }
        else:
            if obi >= 0.0:
                logger.info(
                    "[Sniper] Fase 3 — Rompimento detectado mas OBI=%.3f não confirma MULTDOWN",
                    obi,
                )
                return {
                    **wait,
                    "reason": "Rompimento BB sem confirmação OBI (<0)",
                    "phase": "fase3_obi_block",
                    "diagnostics": diag,
                }

        conf = max(float(config.MIN_CONFIDENCE), 0.82)
        logger.info(
            "[Sniper] Fase 3 — Rompimento detectado -> Comprando %s (OBI=%.3f)",
            side,
            obi,
        )
        self._alert_side = None
        return {
            "signal": side,
            "confidence": conf,
            "mode": "SNIPER",
            "reason": f"BB breakout M5 + OBI ({obi:.3f}) alinhado à maré M15",
            "phase": "fire",
            "diagnostics": diag,
        }
