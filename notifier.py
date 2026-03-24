import asyncio
import html
import logging
from typing import Any, Dict, List, Optional

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


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, float):
        return value
    if value is None or isinstance(value, (bool, int, str)):
        return value
    return str(value)


class Notifier:
    """Alertas: Gestor central (MANAGER_WEBHOOK_URL) e webhook opcional (ALERT_WEBHOOK_URL)."""

    def __init__(self) -> None:
        self._manager_url = (config.MANAGER_WEBHOOK_URL or "").strip()
        self._webhook_url = (config.ALERT_WEBHOOK_URL or "").strip()

    async def _post_manager(
        self,
        *,
        text: str,
        parse_mode: str = "HTML",
        event: str = "message",
        trade_info: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self._manager_url:
            logger.info("[notifier sem gestor] %s", text[:500])
            return
        payload: Dict[str, Any] = {
            "text": text,
            "parse_mode": parse_mode,
            "event": event,
        }
        if trade_info is not None:
            payload["trade_info"] = _json_safe(trade_info)
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                await session.post(
                    self._manager_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
        except Exception as e:
            logger.warning("Falha ao enviar ao gestor (%s): %s", self._manager_url, e)

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
        tasks: List[asyncio.Task] = []
        if self._manager_url:
            tasks.append(
                asyncio.create_task(
                    self._post_manager(text=text, parse_mode=parse_mode, event="message")
                )
            )
        if self._webhook_url:
            tasks.append(asyncio.create_task(self._post_webhook(text)))
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
        if self._manager_url:
            await self._post_manager(
                text=msg,
                parse_mode="HTML",
                event="trade",
                trade_info=trade_info,
            )
        if self._webhook_url:
            await self._post_webhook(msg)
        if not self._manager_url and not self._webhook_url:
            logger.info("%s", msg)

    async def error(self, where: str, err: BaseException) -> None:
        w = html.escape(str(where))
        name = html.escape(type(err).__name__)
        detail = html.escape(str(err))[:3000]
        msg = f"⚠️ <b>Erro</b> — <code>{w}</code>\n<code>{name}</code>: {detail}"
        await self.send(msg[:3500])
