import logging

import numpy as np
import pandas as pd
import ta

import config
from order_book import OrderBookAnalyzer
from sr_detector import SRDetector

logger = logging.getLogger(__name__)


class AIEngine:
    def __init__(self):
        self.ob = OrderBookAnalyzer(window=100)
        self.sr = SRDetector(sensitivity=0.001)
        self.mode = config.AI_MODE

    def detect_regime(self, df):
        adx = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=14)
        adx_val = adx.adx().iloc[-1]
        atr = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close']).average_true_range()
        atr_val = atr.iloc[-1]
        avg_atr = atr.mean()
        if adx_val > 25:
            return "TREND"
        elif atr_val > avg_atr * 1.5:
            return "SCALP"
        else:
            return "SWING"

    def analyze(self, candles, latest_tick):
        if len(candles) < 50:
            return {"signal": "WAIT", "confidence": 0, "mode": "LOADING", "reason": "Carregando dados"}
        df = pd.DataFrame(candles)
        df.columns = ['epoch', 'open', 'high', 'low', 'close']
        for col in ['open', 'high', 'low', 'close']:
            df[col] = pd.to_numeric(df[col])
        _n_before = len(df)
        df.dropna(inplace=True)
        if len(df) < _n_before:
            logger.warning(
                "ai_engine: %s linha(s) removida(s) após OHLC inválidos (corretora)",
                _n_before - len(df),
            )
        self.ob.add_tick(latest_tick)
        self.sr.detect_levels(df['high'].values, df['low'].values, df['close'].values)
        active_mode = self.detect_regime(df) if self.mode == "AUTO" else self.mode
        if active_mode == "TREND":
            return self._trend_signal(df, latest_tick)
        elif active_mode == "SCALP":
            return self._scalp_signal(df, latest_tick)
        else:
            return self._swing_signal(df, latest_tick)

    def _trend_signal(self, df, price):
        ema9 = ta.trend.EMAIndicator(df['close'], window=9).ema_indicator().iloc[-1]
        ema21 = ta.trend.EMAIndicator(df['close'], window=21).ema_indicator().iloc[-1]
        ema50 = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator().iloc[-1]
        adx_ind = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=14)
        adx = adx_ind.adx().iloc[-1]
        dip = adx_ind.adx_pos().iloc[-1]
        dim = adx_ind.adx_neg().iloc[-1]
        macd = ta.trend.MACD(df['close'])
        macd_val = macd.macd().iloc[-1]
        sig_val = macd.macd_signal().iloc[-1]
        score = 0
        if ema9 > ema21 > ema50: score += 0.3
        if adx > 25: score += 0.2
        if dip > dim: score += 0.2
        if macd_val > sig_val: score += 0.15
        if price > ema9: score += 0.15
        if score >= config.MIN_CONFIDENCE:
            return {"signal": "CALL", "confidence": score, "mode": "TREND", "reason": "EMA+ADX+MACD de alta"}
        score2 = 0
        if ema9 < ema21 < ema50: score2 += 0.3
        if adx > 25: score2 += 0.2
        if dim > dip: score2 += 0.2
        if macd_val < sig_val: score2 += 0.15
        if price < ema9: score2 += 0.15
        if score2 >= config.MIN_CONFIDENCE:
            return {"signal": "PUT", "confidence": score2, "mode": "TREND", "reason": "EMA+ADX+MACD de baixa"}
        return {"signal": "WAIT", "confidence": 0, "mode": "TREND", "reason": "Sem sinal"}

    def _scalp_signal(self, df, price):
        rsi = ta.momentum.RSIIndicator(df['close'], window=7).rsi().iloc[-1]
        obi = self.ob.get_obi()
        mom = self.ob.get_momentum(5)
        bb = ta.volatility.BollingerBands(df['close'], window=10)
        bbl = bb.bollinger_lband().iloc[-1]
        bbu = bb.bollinger_hband().iloc[-1]
        score_c = 0
        score_p = 0
        if obi > config.OBI_THRESHOLD: score_c += 0.4
        if rsi < 35: score_c += 0.3
        if mom > 0: score_c += 0.15
        if price <= bbl: score_c += 0.15
        if obi < -config.OBI_THRESHOLD: score_p += 0.4
        if rsi > 65: score_p += 0.3
        if mom < 0: score_p += 0.15
        if price >= bbu: score_p += 0.15
        if score_c >= config.MIN_CONFIDENCE:
            return {"signal": "CALL", "confidence": score_c, "mode": "SCALP", "reason": "OBI+RSI+BB de alta"}
        if score_p >= config.MIN_CONFIDENCE:
            return {"signal": "PUT", "confidence": score_p, "mode": "SCALP", "reason": "OBI+RSI+BB de baixa"}
        return {"signal": "WAIT", "confidence": 0, "mode": "SCALP", "reason": "Sem sinal"}

    def _swing_signal(self, df, price):
        rsi = ta.momentum.RSIIndicator(df['close'], window=14).rsi().iloc[-1]
        stoch = ta.momentum.StochasticOscillator(df['high'], df['low'], df['close'])
        sk = stoch.stoch().iloc[-1]
        sr_info = self.sr.is_near_level(price)
        ema200 = ta.trend.EMAIndicator(df['close'], window=200).ema_indicator().iloc[-1]
        score_c = 0
        score_p = 0
        if rsi < 30: score_c += 0.35
        if sk < 20: score_c += 0.25
        if price > ema200: score_c += 0.2
        if sr_info['near'] and sr_info.get('level', {}).get('type') == 'support':
            score_c += 0.2
        if rsi > 70: score_p += 0.35
        if sk > 80: score_p += 0.25
        if price < ema200: score_p += 0.2
        if sr_info['near'] and sr_info.get('level', {}).get('type') == 'resistance':
            score_p += 0.2
        if score_c >= config.MIN_CONFIDENCE:
            return {"signal": "CALL", "confidence": score_c, "mode": "SWING", "reason": "RSI+Stoch+SR de alta"}
        if score_p >= config.MIN_CONFIDENCE:
            return {"signal": "PUT", "confidence": score_p, "mode": "SWING", "reason": "RSI+Stoch+SR de baixa"}
        return {"signal": "WAIT", "confidence": 0, "mode": "SWING", "reason": "Sem sinal"}
