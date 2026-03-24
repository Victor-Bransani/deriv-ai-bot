import asyncio
import html
import logging
from typing import Any, Callable, Coroutine, List, Optional

import aiohttp

import config

logger = logging.getLogger(__name__)


def format_trade_summary_html(trade_info: dict) -> str:
    """Bloco HTML com saldo, WR na janela, trades e PnL vs abertura do dia."""
    if trade_info.get("balance") is None:
        return ""
    bal = trade_info["balance"]
    wr = trade_info.get("wr_window_pct", 0.0)
    tw = trade_info.get("trades_window", 0)
    tt = trade_info.get("trades_today", 0)
    dp = trade_info.get("daily_pnl", 0.0)
    dpp = trade_info.get("daily_pnl_vs_open_pct", 0.0)
    ref = trade_info.get("day_open_balance", 0.0)
    return (
        f"\n────────────\n"
        f"💰 Saldo: <b>{bal:.2f}</b> USD\n"
        f"📊 WR (janela Kelly): <b>{wr:.1f}%</b> · ops na janela: <b>{tw}</b>\n"
        f"📅 Hoje: <b>{tt}</b> trades fechados · PnL dia: <b>{dp:+.2f}</b> USD "
        f"(<b>{dpp:+.2f}%</b> vs ref. abertura)\n"
        f"🏦 Ref. abertura hoje: <b>{ref:.2f}</b> USD"
    )


class Notifier:
    """Alertas na VPS: Telegram (bot já iniciado) e webhook opcional."""

    def __init__(self) -> None:
        self._telegram_send: Optional[Callable[[str], Coroutine[Any, Any, None]]] = None
        self._webhook_url = (config.ALERT_WEBHOOK_URL or "").strip()

    def bind_telegram(self, send_coro: Callable[[str], Coroutine[Any, Any, None]]) -> None:
        self._telegram_send = send_coro

    async def _post_webhook(self, text: str) -> None:
        if not self._webhook_url:
            return
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                await session.post(
                    self._webhook_url,
                    json={"text": text, "source": "deriv-ai-bot"},
                    headers={"Content-Type": "application/json"},
                )
        except Exception as e:
            logger.warning("Falha ao enviar webhook: %s", e)

    async def send(self, text: str, parse_mode: str = "HTML") -> None:
        tasks: List[Coroutine[Any, Any, None]] = []
        if self._telegram_send:
            tasks.append(self._telegram_send(text, parse_mode))
        if self._webhook_url:
            tasks.append(self._post_webhook(text))
        if not tasks:
            logger.info("%s", text)
            return
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.warning("Falha num canal do notifier: %s", r)

    async def trade_signal(self, trade_info: dict) -> None:
        sym = html.escape(str(trade_info["symbol"]))
        mode = html.escape(str(trade_info["mode"]))
        typ = html.escape(str(trade_info["type"]))
        extra = format_trade_summary_html(trade_info)
        if trade_info.get("won") is None:
            reason = html.escape(str(trade_info["reason"]))
            msg = (
                f"🔔 <b>Sinal {typ}</b>\n"
                f"💹 {sym} | 🧠 {mode}\n"
                f"💵 Entrada: {trade_info['stake']:.2f} USD\n"
                f"🔥 Confiança: {trade_info['confidence']:.1%}\n"
                f"📝 Motivo: {reason}\n"
                f"🕐 {html.escape(str(trade_info['time']))}"
                f"{extra}"
            )
        else:
            emoji = "✅" if trade_info["won"] else "❌"
            msg = (
                f"{emoji} <b>Resultado</b>\n"
                f"💹 {sym} | {typ}\n"
                f"💰 PnL: {trade_info.get('pnl', 0):.2f} USD\n"
                f"🕐 {html.escape(str(trade_info['time']))}"
                f"{extra}"
            )
        await self.send(msg)

    async def error(self, where: str, err: BaseException) -> None:
        w = html.escape(str(where))
        name = html.escape(type(err).__name__)
        detail = html.escape(str(err))[:3000]
        msg = f"⚠️ <b>Erro</b> — <code>{w}</code>\n<code>{name}</code>: {detail}"
        await self.send(msg[:3500])
