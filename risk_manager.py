import datetime
import logging
from collections import deque
from typing import Optional, Tuple

import config
import user_settings
from kelly import TradeOutcome, compute_kelly_stake_fraction

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

    def _fixed_fraction_stake(self, balance: float) -> float:
        mn = user_settings.effective_float("min_stake", config.MIN_STAKE)
        stake = balance * config.RISK_PER_TRADE
        stake = max(mn, min(stake, config.MAX_STAKE))
        return round(stake, 2)

    def calc_stake(self, balance: float) -> float:
        self._ensure_kelly_window()
        self._peak_balance = max(self._peak_balance, balance)
        drawdown = 0.0
        if self._peak_balance > 1e-12:
            drawdown = 1.0 - (balance / self._peak_balance)

        k_on = user_settings.effective_bool("kelly_enabled", config.KELLY_ENABLED)
        k_min = user_settings.effective_int("kelly_min_trades", config.KELLY_MIN_TRADES)

        if not k_on or len(self._kelly_history) < k_min:
            self._last_kelly_meta = {
                "mode": "warmup_fixed",
                "n": len(self._kelly_history),
                "min_needed": k_min,
            }
            return self._fixed_fraction_stake(balance)

        f, meta = compute_kelly_stake_fraction(
            self._kelly_history,
            default_b=user_settings.effective_float(
                "kelly_default_win_payoff", config.KELLY_DEFAULT_WIN_PAYOFF
            ),
            kelly_fraction=user_settings.effective_float(
                "kelly_fraction", config.KELLY_FRACTION
            ),
            use_wilson_p=user_settings.effective_bool(
                "kelly_use_wilson", config.KELLY_USE_WILSON
            ),
            alpha_prior=config.KELLY_PRIOR_WINS,
            beta_prior=config.KELLY_PRIOR_LOSSES,
            max_full_kelly=user_settings.effective_float(
                "kelly_cap_full_fraction", config.KELLY_CAP_FULL_FRACTION
            ),
            drawdown=drawdown,
            drawdown_soft_start=user_settings.effective_float(
                "kelly_dd_soft_start", config.KELLY_DD_SOFT_START
            ),
            drawdown_min_scale=user_settings.effective_float(
                "kelly_dd_min_scale", config.KELLY_DD_MIN_SCALE
            ),
        )
        self._last_kelly_meta = meta

        if f <= 0.0 or meta.get("edge") == "none_or_negative":
            mn = user_settings.effective_float("min_stake", config.MIN_STAKE)
            stake = max(
                mn,
                min(balance * config.RISK_PER_TRADE * 0.5, config.MAX_STAKE),
            )
            self._last_kelly_meta["fallback"] = "sem_margem_kelly"
            return round(stake, 2)

        max_f = user_settings.effective_float(
            "kelly_max_bankroll_fraction", config.KELLY_MAX_BANKROLL_FRACTION
        )
        f = min(f, max_f)
        mn = user_settings.effective_float("min_stake", config.MIN_STAKE)
        stake = balance * f
        stake = max(mn, min(stake, config.MAX_STAKE))
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Kelly stake meta: %s", self._last_kelly_meta)
        else:
            logger.info(
                "Stake Kelly: f=%.4f banca, p=%s, b=%s, n=%s",
                f,
                meta.get("p_used"),
                meta.get("b_hat"),
                meta.get("n"),
            )
        return round(stake, 2)

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
