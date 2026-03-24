import asyncio
import datetime
import html
import logging
import os
import signal
from typing import Optional

from aiohttp import web

import config
import user_settings
from ai_engine import AIEngine
from deriv_client import DerivClient, DerivClientError
from notifier import Notifier
from risk_manager import RiskManager
from telegram_bot import TelegramInterface

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("deriv_ai_bot")


class DerivAIBot:
    def __init__(self) -> None:
        self.notifier = Notifier()
        self.deriv = DerivClient()
        self.ai = AIEngine()
        self.risk = RiskManager()
        self.tg = TelegramInterface(self, notifier=self.notifier)
        self.candles: list = []
        self._stop = asyncio.Event()
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

    def request_stop(self) -> None:
        self._stop.set()
        self.state["running"] = False

    async def start(self) -> None:
        await self.deriv.connect()
        self.state["balance"] = self.deriv.balance
        self.risk.set_balance(self.deriv.balance)
        self.risk.ensure_day_opening_balance(self.deriv.balance)

        self.notifier.bind_telegram(self.tg.telegram_sender())

        async with self.tg.app:
            await self.tg.app.start()
            await self.tg.app.updater.start_polling()

            auto = "ligada" if config.AUTO_START_TRADING else "desligada"
            await self.notifier.send(
                f"🤖 <b>Deriv AI — VPS</b>\n"
                f"💰 Saldo: {self.deriv.balance:.2f} USD\n"
                f"🧠 Modo: {config.AI_MODE}\n"
                f"💹 Ativo: {config.ACTIVE_SYMBOL}\n"
                f"▶️ Operação automática: <b>{auto}</b> (env <code>AUTO_START_TRADING</code>)\n"
                f"WebSocket ativo. Use /start ou o menu para controlar."
            )

            try:
                await self.trading_loop()
            finally:
                await self.tg.app.updater.stop()
                await self.tg.app.stop()

        await self.deriv.disconnect()

    async def trading_loop(self) -> None:
        last_trade_time = 0.0
        while not self._stop.is_set():
            try:
                if self.state["running"]:
                    now = asyncio.get_event_loop().time()
                    if now - last_trade_time >= config.TRADE_COOLDOWN:
                        traded = await self.run_cycle()
                        if traded:
                            last_trade_time = asyncio.get_event_loop().time()
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
        symbols_map = {
            "V10": "R_10",
            "V25": "R_25",
            "V50": "R_50",
            "V75": "R_75",
            "V100": "R_100",
            "BOOM500": "BOOM500",
            "CRASH500": "CRASH500",
            "STEP": "stpRNG",
        }
        deriv_symbol = symbols_map.get(symbol, "R_75")
        try:
            self.candles = await self.deriv.get_candles(
                deriv_symbol, count=200, tf=config.CANDLE_TF
            )
        except DerivClientError as e:
            logger.warning("get_candles: %s", e)
            await self.notifier.error("get_candles", e)
            try:
                await self.deriv.ensure_connected()
            except Exception as ex:
                logger.warning("ensure_connected: %s", ex)
            return False
        if not self.candles:
            return False
        latest_price = float(self.candles[-1]["close"])
        result = await asyncio.get_running_loop().run_in_executor(
            None, self.ai.analyze, self.candles, latest_price
        )
        self.state["last_signal"] = result["signal"]
        self.state["last_confidence"] = result["confidence"]
        self.state["ai_mode"] = result["mode"]
        if result["signal"] == "WAIT":
            return False
        can, reason = self.risk.can_trade(result["confidence"])
        if not can:
            logger.info("Trade bloqueado: %s", reason)
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
            buy_result = await self.deriv.buy_contract(
                result["signal"], stake, config.DURATION, deriv_symbol
            )
        except DerivClientError as e:
            await self.notifier.error("buy_contract", e)
            await self.deriv.ensure_connected()
            return False
        if buy_result:
            won = buy_result.get("profit", 0) > 0
            pnl = float(buy_result.get("profit", 0))
            self.risk.record_trade(won, pnl, stake=stake)
            self.state["daily_pnl"] += pnl
            trade_info["won"] = won
            trade_info["pnl"] = pnl
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
