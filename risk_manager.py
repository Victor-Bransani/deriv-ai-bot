import datetime
import logging
from collections import deque
from typing import Optional, Tuple

import config
import user_settings
from kelly import TradeOutcome

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(self):
        self.daily_loss = 0.0
        self.daily_trades = 0
        self.consecutive_loss = 0
        self.initial_balance = 0.0
        self.last_reset = datetime.date.today()
        self.paused = False
        self.pause_reason = ""
        self._peak_balance = 0.0
        self.day_start_balance = 0.0
        self._kelly_maxlen = user_settings.effective_int(
            "kelly_window", config.KELLY_WINDOW
        )
        self._kelly_history: deque[TradeOutcome] = deque(maxlen=self._kelly_maxlen)
        self._last_kelly_meta: dict = {}
        self._notify_streak_pause = False

    def _ensure_kelly_window(self) -> None:
        w = user_settings.effective_int("kelly_window", config.KELLY_WINDOW)
        w = max(5, min(500, w))
        if w != self._kelly_maxlen:
            old = list(self._kelly_history)
            self._kelly_maxlen = w
            self._kelly_history = deque(old[-w:], maxlen=w)

    def set_balance(self, bal):
        if self.initial_balance == 0:
            self.initial_balance = bal
        self._peak_balance = max(self._peak_balance, bal)

    def _reset_daily(self):
        today = datetime.date.today()
        if today > self.last_reset:
            self.daily_loss = 0.0
            self.daily_trades = 0
            self.last_reset = today
            self.paused = False
            self.pause_reason = ""
            self.day_start_balance = 0.0
            self.consecutive_loss = 0
            self._notify_streak_pause = False

    def on_calendar_day_rollover(self) -> None:
        """Primeiro ciclo após mudança de dia (main zera PnL do estado)."""
        self._reset_daily()

    def ensure_day_opening_balance(self, balance: float) -> None:
        """Congela referência do dia (abertura) na primeira leitura de saldo útil."""
        if balance > 0 and self.day_start_balance <= 0:
            self.day_start_balance = balance

    def can_trade(self, confidence):
        self._reset_daily()
        if self.paused:
            return False, (self.pause_reason or "Pausa ativa")
        if self.daily_trades >= config.MAX_DAILY_TRADES:
            return False, "Limite diário de trades atingido"
        if self.daily_loss >= config.MAX_DAILY_LOSS:
            return False, "Limite de perda diária atingido"
        if self.consecutive_loss >= config.MAX_CONSECUTIVE_LOSS:
            if not self.paused:
                self._notify_streak_pause = True
            self.paused = True
            n = config.MAX_CONSECUTIVE_LOSS
            self.pause_reason = (
                f"{n} perdas seguidas — pausa até virar o dia (meia-noite no servidor) "
                f"ou reiniciar o serviço; o contador de sequência zera no novo dia."
            )
            return False, f"Pausa: {n} perdas seguidas"
        if confidence < config.MIN_CONFIDENCE:
            return False, "Confiança da IA abaixo do mínimo"
        return True, "OK"

    def evaluate_tp_sl(self, balance: float, daily_pnl: float) -> Tuple[bool, Optional[str]]:
        """
        TP/SL em percentual da banca de abertura do dia (day_start_balance).
        Valores em fração: 0.05 = 5%. 0 em config/telegram = desligado.
        """
        tp = user_settings.effective_float("tp_daily_pct", config.TP_DAILY_PCT)
        sl = user_settings.effective_float("sl_daily_pct", config.SL_DAILY_PCT)
        ref = self.day_start_balance
        if ref <= 1e-9 or (tp <= 0 and sl <= 0):
            return False, None
        pnl_pct = daily_pnl / ref
        if tp > 0 and pnl_pct >= tp:
            self.paused = True
            self.pause_reason = (
                f"TP diário: lucro {pnl_pct:.2%} ≥ {tp:.2%} (ref. abertura {ref:.2f} USD)"
            )
            return True, self.pause_reason
        if sl > 0 and pnl_pct <= -sl:
            self.paused = True
            self.pause_reason = (
                f"SL diário: perda {pnl_pct:.2%} ≤ {-sl:.2%} (ref. abertura {ref:.2f} USD)"
            )
            return True, self.pause_reason
        return False, None

    def build_trade_summary(self, balance: float, daily_pnl: float) -> dict:
        n = len(self._kelly_history)
        wins = sum(1 for t in self._kelly_history if t.won)
        wr = (wins / n * 100.0) if n else 0.0
        ref = self.day_start_balance if self.day_start_balance > 0 else balance
        pnl_vs_open = (daily_pnl / ref * 100.0) if ref > 1e-9 else 0.0
        return {
            "balance": balance,
            "wr_window_pct": wr,
            "trades_window": n,
            "trades_today": self.daily_trades,
            "daily_pnl": daily_pnl,
            "daily_pnl_vs_open_pct": pnl_vs_open,
            "day_open_balance": ref,
        }

    def calc_stake(self, balance: float) -> float:
        """
        stake = max(1.00, banca × MAX_STAKE_PCT), tipicamente 1% (mín. 1 USD na Deriv),
        limitado a MAX_STAKE (teto de liquidez institucional).
        """
        self._ensure_kelly_window()
        self._peak_balance = max(self._peak_balance, balance)
        stake = max(1.0, float(balance) * float(config.MAX_STAKE_PCT))
        stake = min(stake, float(config.MAX_STAKE))
        self._last_kelly_meta = {
            "mode": "fixed_max_stake_pct",
            "max_stake_pct": config.MAX_STAKE_PCT,
            "cap_max_stake": config.MAX_STAKE,
        }
        logger.info(
            "Stake sniper: %.2f USD (banca %.2f × %.2f%% da banca, teto %.2f)",
            round(stake, 2),
            balance,
            config.MAX_STAKE_PCT * 100.0,
            config.MAX_STAKE,
        )
        return round(stake, 2)

    def record_ghost_trade_release(self, contract_id: int, stake: float) -> None:
        """
        Timeout de segurança: sem fechamento explícito via WS dentro do prazo.
        Não altera sequência de perdas nem histórico Kelly; apenas liberta o ciclo.
        """
        logger.warning(
            "Ghost trade: timeout WS contract_id=%s (stake ref=%.2f) — estado libertado, empate operacional",
            contract_id,
            stake,
        )

    def record_trade(self, won, pnl, stake: float):
        self._ensure_kelly_window()
        self.daily_trades += 1
        if not won:
            self.daily_loss += abs(pnl) / (self.initial_balance or 1)
            self.consecutive_loss += 1
        else:
            self.consecutive_loss = 0
        st = max(stake, 1e-9)
        self._kelly_history.append(
            TradeOutcome(stake=st, profit=float(pnl), won=bool(won))
        )

    def consume_streak_pause_notification(self) -> bool:
        """Uma vez após entrar em pausa por sequência de perdas (para Telegram)."""
        if self._notify_streak_pause:
            self._notify_streak_pause = False
            return True
        return False

    def get_stats(self):
        snap = user_settings.kelly_snapshot()
        bank = user_settings.bank_snapshot()
        out = {
            "daily_trades": self.daily_trades,
            "daily_loss_pct": self.daily_loss * 100,
            "consecutive_loss": self.consecutive_loss,
            "max_consecutive_before_pause": config.MAX_CONSECUTIVE_LOSS,
            "paused": self.paused,
            "pause_reason": self.pause_reason,
            "kelly_trades_in_window": len(self._kelly_history),
            "kelly_last": self._last_kelly_meta,
            "kelly_effective": snap,
            "day_open_balance": self.day_start_balance,
            "bank_effective": bank,
        }
        return out
