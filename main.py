import asyncio
import datetime
import html
import logging
import os
import signal
from functools import partial
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

from aiohttp import web

import config
import user_settings
from ai_engine import AIEngine
from deriv_client import DerivClient, DerivClientError
from notifier import Notifier
from risk_manager import RiskManager
from telegram_bot import TelegramInterface
from tick_csv_logger import CycleCsvWriter, TickCsvWriter

logger = logging.getLogger("deriv_ai_bot")


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(config.LOG_LEVEL)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for h in list(root.handlers):
        root.removeHandler(h)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)
    if config.BOT_LOG_FILE:
        log_path = Path(config.BOT_LOG_FILE)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            log_path,
            maxBytes=config.BOT_LOG_MAX_BYTES,
            backupCount=config.BOT_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)
        logger.info("Log em ficheiro: %s", log_path.resolve())


class DerivAIBot:
    SYMBOLS_MAP = {
        "V10": "R_10",
        "V25": "R_25",
        "V50": "R_50",
        "V75": "R_75",
        "V100": "R_100",
        "BOOM500": "BOOM500",
        "CRASH500": "CRASH500",
        "STEP": "stpRNG",
    }

    def __init__(self) -> None:
        self.notifier = Notifier()
        self.deriv = DerivClient()
        self.ai = AIEngine()
        self.risk = RiskManager()
        self.tg = TelegramInterface(self, notifier=self.notifier)
        self._stop = asyncio.Event()
        self._last_idle_log_mono: float = 0.0
        self._tick_queue: Optional[asyncio.Queue] = None
        self._tick_consumer_task: Optional[asyncio.Task] = None
        self._tick_writer: Optional[TickCsvWriter] = None
        self._cycle_writer: Optional[CycleCsvWriter] = None
        self.state = {
            "running": bool(config.AUTO_START_TRADING),
            "ai_mode": config.AI_MODE,
            "symbol": config.ACTIVE_SYMBOL,
            "balance": 0.0,
            "daily_pnl": 0.0,
            "last_signal": "WAIT",
            "last_confidence": 0.0,
        }
        self._stats_day: Optional[datetime.date] = None

    def _deriv_symbol(self) -> str:
        return self.SYMBOLS_MAP.get(self.state["symbol"], "R_75")

    async def _consume_ticks_csv(self) -> None:
        if not self._tick_writer or not self._tick_queue:
            return
        while not self._stop.is_set():
            try:
                msg = await asyncio.wait_for(self._tick_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            try:
                await self._tick_writer.append_ws_tick_message(msg)
            except Exception as e:
                logger.exception("Erro ao gravar tick CSV: %s", e)

    async def _write_cycle_csv(
        self,
        *,
        deriv_symbol: str,
        symbol_ui: str,
        result: Optional[Dict[str, Any]],
        blocked_reason: str = "",
        err_note: str = "",
    ) -> None:
        if not self._cycle_writer:
            return
        row: Dict[str, Any] = {
            "symbol_ui": symbol_ui,
            "symbol_deriv": deriv_symbol,
            "running": self.state["running"],
            "balance": round(float(self.state["balance"]), 2),
            "trade_blocked_reason": blocked_reason or err_note,
        }
        if result:
            row["phase"] = result.get("phase", "")
            row["signal"] = result.get("signal", "")
            row["confidence"] = result.get("confidence", "")
            rsn = result.get("reason", "")
            if err_note and not rsn:
                rsn = err_note
            row["reason"] = rsn
            d = result.get("diagnostics") or {}
            for k, v in d.items():
                row[k] = v
        else:
            row["phase"] = "error"
            row["signal"] = "N/A"
            row["confidence"] = ""
            row["reason"] = err_note or "sem resultado da IA"
        try:
            await self._cycle_writer.append_cycle(row)
        except Exception as e:
            logger.warning("Gravação cycle CSV: %s", e)

    def request_stop(self) -> None:
        self._stop.set()
        self.state["running"] = False

    async def start(self) -> None:
        await self.deriv.connect()
        self.state["balance"] = self.deriv.balance
        self.risk.set_balance(self.deriv.balance)
        self.risk.ensure_day_opening_balance(self.deriv.balance)

        self.notifier.bind_telegram(self.tg.telegram_sender())

        if config.CYCLE_CSV_ENABLED:
            self._cycle_writer = CycleCsvWriter(config.DATA_DIR)
            logger.info("CSV de ciclos (features): %s", config.DATA_DIR.resolve())

        if config.TICK_CSV_ENABLED:
            self._tick_writer = TickCsvWriter(config.DATA_DIR)
            qmax = max(1_000, int(config.TICK_QUEUE_MAX))
            self._tick_queue = asyncio.Queue(maxsize=qmax)
            self.deriv.set_tick_queue(self._tick_queue)
            self._tick_consumer_task = asyncio.create_task(
                self._consume_ticks_csv(), name="tick-csv-writer"
            )
            logger.info(
                "CSV de ticks: %s (fila=%s) — stream Deriv",
                config.DATA_DIR.resolve(),
                qmax,
            )
            try:
                await self.deriv.subscribe_tick_stream(self._deriv_symbol())
            except Exception as e:
                logger.warning("Subscrição de ticks para CSV falhou: %s", e)

        async with self.tg.app:
            await self.tg.app.start()
            await self.tg.app.updater.start_polling()

            auto = "ligada" if config.AUTO_START_TRADING else "desligada"
            await self.notifier.send(
                f"🤖 <b>Deriv AI — VPS</b>\n"
                f"💰 Saldo: {self.deriv.balance:.2f} USD\n"
                f"🧠 Motor: Sniper multiplicadores (M15+M5)\n"
                f"💹 Ativo: {config.ACTIVE_SYMBOL}\n"
                f"▶️ Operação automática: <b>{auto}</b> (env <code>AUTO_START_TRADING</code>)\n"
                f"WebSocket ativo. Use /start ou o menu para controlar."
            )

            try:
                await self.trading_loop()
            finally:
                if self._tick_consumer_task:
                    self._tick_consumer_task.cancel()
                    try:
                        await self._tick_consumer_task
                    except asyncio.CancelledError:
                        pass
                await self.tg.app.updater.stop()
                await self.tg.app.stop()

        await self.deriv.disconnect()

    async def trading_loop(self) -> None:
        last_trade_time = 0.0
        while not self._stop.is_set():
            try:
                loop_time = asyncio.get_event_loop().time()
                if self.state["running"]:
                    if loop_time - last_trade_time >= config.TRADE_COOLDOWN:
                        traded = await self.run_cycle()
                        if traded:
                            last_trade_time = asyncio.get_event_loop().time()
                else:
                    if (
                        loop_time - self._last_idle_log_mono
                        >= config.IDLE_TRADING_LOG_INTERVAL_SEC
                    ):
                        self._last_idle_log_mono = loop_time
                        logger.info(
                            "[Estado] Trading automático DESLIGADO — sem análise de mercado nem "
                            "novas linhas em cycles_*.csv. Use /start no Telegram ou "
                            "AUTO_START_TRADING=true no .env"
                        )
                await asyncio.wait_for(self._stop.wait(), timeout=10.0)
                break
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Erro no loop de trading: %s", e)
                try:
                    await self.notifier.error("trading_loop", e)
                except Exception:
                    pass
                await asyncio.sleep(30)

    async def run_cycle(self) -> bool:
        td = datetime.date.today()
        if self._stats_day != td:
            self._stats_day = td
            self.state["daily_pnl"] = 0.0
            self.risk.on_calendar_day_rollover()

        symbol = self.state["symbol"]
        deriv_symbol = self._deriv_symbol()
        try:
            candles_m15, candles_m5 = await asyncio.gather(
                self.deriv.get_candles(
                    deriv_symbol, count=200, tf=config.CANDLE_GRANULARITY_M15
                ),
                self.deriv.get_candles(
                    deriv_symbol, count=200, tf=config.CANDLE_GRANULARITY_M5
                ),
            )
        except DerivClientError as e:
            logger.warning("get_candles: %s", e)
            await self.notifier.error("get_candles", e)
            try:
                await self.deriv.ensure_connected()
            except Exception as ex:
                logger.warning("ensure_connected: %s", ex)
            await self._write_cycle_csv(
                deriv_symbol=deriv_symbol,
                symbol_ui=symbol,
                result=None,
                err_note="get_candles falhou",
            )
            return False
        if not candles_m15 or not candles_m5:
            await self._write_cycle_csv(
                deriv_symbol=deriv_symbol,
                symbol_ui=symbol,
                result=None,
                err_note="velas vazias (M15/M5)",
            )
            return False
        latest_price = float(candles_m5[-1]["close"])
        result: Optional[Dict[str, Any]] = None
        blocked_reason = ""
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                partial(self.ai.analyze, candles_m15, candles_m5, latest_price),
            )
            self.state["last_signal"] = result["signal"]
            self.state["last_confidence"] = result["confidence"]
            self.state["ai_mode"] = result.get("mode", "SNIPER")

            d = result.get("diagnostics") or {}
            logger.info(
                "[Ciclo] deriv=%s running=%s balance=%.2f phase=%s signal=%s conf=%.3f | "
                "m15_tide=%s rsi_m5=%s obi=%s m5_close=%s alert=%s macd_cross=%s "
                "macd_favors=%s bb_up=%s bb_dn=%s | reason=%s",
                deriv_symbol,
                self.state["running"],
                float(self.state["balance"]),
                result.get("phase", ""),
                result.get("signal", ""),
                float(result.get("confidence") or 0.0),
                d.get("m15_tide", ""),
                d.get("rsi_m5", ""),
                d.get("obi", ""),
                d.get("m5_close", ""),
                d.get("alert_side", ""),
                d.get("macd_cross", ""),
                d.get("macd_favors", ""),
                d.get("bb_breakout_up", ""),
                d.get("bb_breakout_down", ""),
                (result.get("reason") or "")[:200],
            )

            if result["signal"] == "WAIT":
                return False
            can, reason = self.risk.can_trade(result["confidence"])
            if not can:
                logger.info("Trade bloqueado: %s", reason)
                blocked_reason = str(reason)
                if self.risk.consume_streak_pause_notification():
                    await self.notifier.send(
                        "🛑 <b>Pausa por perdas seguidas</b>\n"
                        f"{html.escape(self.risk.pause_reason)}\n\n"
                        "<i>Novas ordens ficam bloqueadas enquanto a pausa estiver ativa. "
                        "Use /status para ver o motivo. No dia seguinte o contador reinicia "
                        "(meia-noite conforme o relógio do servidor).</i>"
                    )
                return False
            try:
                balance = await self.deriv.get_balance()
            except DerivClientError as e:
                await self.notifier.error("get_balance", e)
                await self.deriv.ensure_connected()
                blocked_reason = f"get_balance: {e}"
                return False
            self.state["balance"] = balance
            self.risk.ensure_day_opening_balance(balance)
            stake = self.risk.calc_stake(balance)
            trade_info = {
                "type": result["signal"],
                "symbol": symbol,
                "mode": result["mode"],
                "stake": stake,
                "confidence": result["confidence"],
                "reason": result["reason"],
                "time": datetime.datetime.now().strftime("%H:%M:%S"),
                "won": None,
            }
            trade_info.update(
                self.risk.build_trade_summary(balance, self.state["daily_pnl"])
            )
            await self.tg.send_alert(trade_info)
            try:
                placed = await self.deriv.buy_multiplier_execute(
                    result["signal"], stake, deriv_symbol
                )
            except DerivClientError as e:
                await self.notifier.error("buy_multiplier_execute", e)
                await self.deriv.ensure_connected()
                blocked_reason = f"buy_multiplier_execute: {e}"
                return False
            if not placed:
                blocked_reason = "buy_multiplier_execute retornou None (proposal/buy)"
                return False
            contract_id, buy_price = placed
            buy_result = None
            try:
                buy_result = await asyncio.wait_for(
                    self.deriv.wait_for_result(contract_id, buy_price),
                    timeout=config.GHOST_TRADE_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "Timeout de segurança aguardando WS (contract_id=%s) — consultando profit_table",
                    contract_id,
                )
                buy_result = await self.deriv.get_contract_result(
                    contract_id, buy_price
                )
                if buy_result.get("settled"):
                    logger.info(
                        "Contrato %s encontrado em profit_table após timeout",
                        contract_id,
                    )
                else:
                    self.risk.record_ghost_trade_release(contract_id, stake)
                    buy_result = {
                        "contract_id": contract_id,
                        "profit": 0.0,
                        "won": False,
                        "buy_price": buy_price,
                        "ghost": True,
                    }
            if buy_result:
                if buy_result.get("ghost"):
                    won = False
                    pnl = 0.0
                else:
                    won = buy_result.get("profit", 0) > 0
                    pnl = float(buy_result.get("profit", 0))
                if not buy_result.get("ghost"):
                    self.risk.record_trade(won, pnl, stake=stake)
                self.state["daily_pnl"] += pnl
                trade_info["won"] = won
                trade_info["pnl"] = pnl
                if buy_result.get("ghost"):
                    trade_info["reason"] = (
                        str(trade_info.get("reason", ""))
                        + " | encerramento: timeout WS (ghost, PnL tratado como 0)"
                    )
                trade_info.update(
                    self.risk.build_trade_summary(balance, self.state["daily_pnl"])
                )
                await self.tg.send_alert(trade_info)
                hit, tp_sl_reason = self.risk.evaluate_tp_sl(
                    balance, self.state["daily_pnl"]
                )
                if hit and tp_sl_reason:
                    self.state["running"] = False
                    await self.notifier.send(
                        "🛑 <b>Gestão de banca (TP/SL diário)</b>\n"
                        f"{html.escape(tp_sl_reason)}\n\n"
                        "Trading pausado. Use /bank para rever limites ou /start após ajustar."
                    )
            return True
        finally:
            if result is not None:
                await self._write_cycle_csv(
                    deriv_symbol=deriv_symbol,
                    symbol_ui=symbol,
                    result=result,
                    blocked_reason=blocked_reason,
                )


async def health_server() -> None:
    async def handle(request):
        return web.Response(text="Bot operacional")

    app = web.Application()
    app.router.add_get("/", handle)
    app.router.add_get("/health", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("HTTP health em 0.0.0.0:%s (/ e /health)", port)


async def main() -> None:
    configure_logging()
    user_settings.load()
    await health_server()
    bot = DerivAIBot()
    loop = asyncio.get_running_loop()

    def _sig() -> None:
        logger.info("Sinal de parada recebido")
        bot.request_stop()

    try:
        loop.add_signal_handler(signal.SIGINT, _sig)
        loop.add_signal_handler(signal.SIGTERM, _sig)
    except NotImplementedError:
        pass

    try:
        await bot.start()
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.exception("Falha fatal: %s", e)
        try:
            await bot.notifier.error("main", e)
        except Exception:
            pass
        raise


if __name__ == "__main__":
    asyncio.run(main())
