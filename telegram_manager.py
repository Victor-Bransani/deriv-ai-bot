"""
Gestor central: único processo com Telegram + receptor HTTP para alertas dos operários.

Executar: python telegram_manager.py
Requer .env com TELEGRAM_TOKEN, CHAT_ID e URLs dos operários (WORKER_V10_URL, ...).
"""
from __future__ import annotations

import asyncio
import html
import logging
import os
import signal
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from aiohttp import web
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("telegram_manager")

WORKER_TIMEOUT = aiohttp.ClientTimeout(total=2.0)


def load_workers() -> Dict[str, str]:
    """Mapeamento símbolo UI → URL base do operário (sem path final)."""
    return {
        "V10": os.getenv("WORKER_V10_URL", "http://127.0.0.1:8081").rstrip("/"),
        "V25": os.getenv("WORKER_V25_URL", "http://127.0.0.1:8082").rstrip("/"),
        "V50": os.getenv("WORKER_V50_URL", "http://127.0.0.1:8083").rstrip("/"),
        "V75": os.getenv("WORKER_V75_URL", "http://127.0.0.1:8084").rstrip("/"),
    }


WORKERS = load_workers()


def _chat_allowed(update: Update) -> bool:
    if not update.effective_chat:
        return False
    return str(update.effective_chat.id).strip() == str(config.CHAT_ID).strip()


def _norm_symbol(raw: str) -> Optional[str]:
    s = raw.strip().upper()
    if s in WORKERS:
        return s
    return None


async def _fetch_status(
    session: aiohttp.ClientSession, label: str, base_url: str
) -> Tuple[str, Optional[Dict[str, Any]], Optional[str]]:
    url = f"{base_url}/status"
    try:
        async with session.get(url, timeout=WORKER_TIMEOUT) as resp:
            if resp.status != 200:
                return label, None, f"HTTP {resp.status}"
            data = await resp.json()
            return label, data, None
    except asyncio.TimeoutError:
        return label, None, "timeout"
    except Exception as e:
        return label, None, str(e)[:200]


async def _post_control(
    session: aiohttp.ClientSession, base_url: str, path: str
) -> Tuple[bool, str]:
    url = f"{base_url}{path}"
    try:
        async with session.post(url, timeout=WORKER_TIMEOUT) as resp:
            ok = resp.status == 200
            body = (await resp.text())[:100]
            return ok, body or str(resp.status)
    except asyncio.TimeoutError:
        return False, "timeout"
    except Exception as e:
        return False, str(e)[:200]


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not _chat_allowed(update):
        return
    session: aiohttp.ClientSession = context.application.bot_data["http_session"]
    tasks = [
        _fetch_status(session, sym, url) for sym, url in WORKERS.items()
    ]
    results = await asyncio.gather(*tasks)
    lines: List[str] = ["📊 <b>Status global (operários)</b>\n"]
    total_pnl = 0.0
    any_online = False
    for sym, data, err in results:
        if err or data is None:
            lines.append(f"• <b>{html.escape(sym)}</b>: <i>Offline</i> — {html.escape(err or '?')}")
            continue
        any_online = True
        try:
            pnl = float(data.get("daily_pnl", 0))
        except (TypeError, ValueError):
            pnl = 0.0
        total_pnl += pnl
        run = "🟢" if data.get("running") else "⏸"
        lines.append(
            f"• <b>{html.escape(sym)}</b> {run} saldo <code>{float(data.get('balance', 0)):.2f}</code> "
            f"PnL dia <code>{pnl:+.2f}</code> · último <code>{html.escape(str(data.get('last_signal', '')))}</code>"
        )
    lines.append(f"\n<b>Σ PnL dia (soma)</b>: <code>{total_pnl:+.2f}</code> USD")
    if not any_online:
        lines.append("\n<i>Nenhum operário respondeu dentro do timeout.</i>")
    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML
    )


async def cmd_stop_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not _chat_allowed(update):
        return
    session: aiohttp.ClientSession = context.application.bot_data["http_session"]
    lines = ["⏹ <b>POST /stop em todos</b>\n"]
    for sym, url in WORKERS.items():
        ok, detail = await _post_control(session, url, "/stop")
        icon = "✅" if ok else "❌"
        lines.append(f"{icon} {html.escape(sym)}: {html.escape(detail)}")
    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML
    )


async def cmd_start_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not _chat_allowed(update):
        return
    session: aiohttp.ClientSession = context.application.bot_data["http_session"]
    lines = ["▶️ <b>POST /start em todos</b>\n"]
    for sym, url in WORKERS.items():
        ok, detail = await _post_control(session, url, "/start")
        icon = "✅" if ok else "❌"
        lines.append(f"{icon} {html.escape(sym)}: {html.escape(detail)}")
    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML
    )


async def cmd_stop_one(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not _chat_allowed(update):
        return
    if not context.args:
        await update.effective_message.reply_text(
            "Uso: <code>/stop V75</code> ou <code>/stop_all</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    sym = _norm_symbol(context.args[0])
    if not sym:
        await update.effective_message.reply_text("Símbolo inválido. Use V10, V25, V50 ou V75.")
        return
    session: aiohttp.ClientSession = context.application.bot_data["http_session"]
    url = WORKERS[sym]
    ok, detail = await _post_control(session, url, "/stop")
    icon = "✅" if ok else "❌"
    await update.effective_message.reply_text(
        f"{icon} <b>{sym}</b> POST /stop — {html.escape(detail)}",
        parse_mode=ParseMode.HTML,
    )


async def cmd_start_one(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not _chat_allowed(update):
        return
    if not context.args:
        await update.effective_message.reply_text(
            "Uso: <code>/start V75</code> ou <code>/start_all</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    sym = _norm_symbol(context.args[0])
    if not sym:
        await update.effective_message.reply_text("Símbolo inválido. Use V10, V25, V50 ou V75.")
        return
    session: aiohttp.ClientSession = context.application.bot_data["http_session"]
    url = WORKERS[sym]
    ok, detail = await _post_control(session, url, "/start")
    icon = "✅" if ok else "❌"
    await update.effective_message.reply_text(
        f"{icon} <b>{sym}</b> POST /start — {html.escape(detail)}",
        parse_mode=ParseMode.HTML,
    )


async def handle_alert(request: web.Request) -> web.Response:
    tg_app: Application = request.app["tg_app"]
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="JSON inválido")
    text = data.get("text")
    if not text or not isinstance(text, str):
        return web.Response(status=400, text="campo 'text' obrigatório")
    parse_mode = data.get("parse_mode") or ParseMode.HTML
    if not config.CHAT_ID or not config.TELEGRAM_TOKEN:
        logger.error("CHAT_ID ou TELEGRAM_TOKEN não configurados")
        return web.Response(status=500, text="telegram não configurado")
    try:
        await tg_app.bot.send_message(
            chat_id=config.CHAT_ID,
            text=text[:4096],
            parse_mode=parse_mode,
        )
    except Exception as e:
        logger.exception("Falha ao enviar para Telegram: %s", e)
        return web.Response(status=500, text="telegram send falhou")
    return web.Response(status=200, text="ok")


async def run_manager() -> None:
    if not config.TELEGRAM_TOKEN:
        raise SystemExit("TELEGRAM_TOKEN não definido no .env")
    if not config.CHAT_ID:
        raise SystemExit("CHAT_ID não definido no .env")

    port = int(os.getenv("MANAGER_PORT", "8000"))

    tg_app = (
        Application.builder()
        .token(config.TELEGRAM_TOKEN)
        .concurrent_updates(True)
        .build()
    )
    tg_app.add_handler(CommandHandler("status", cmd_status))
    tg_app.add_handler(CommandHandler("stop_all", cmd_stop_all))
    tg_app.add_handler(CommandHandler("start_all", cmd_start_all))
    tg_app.add_handler(CommandHandler("stop", cmd_stop_one))
    tg_app.add_handler(CommandHandler("start", cmd_start_one))

    http_session = aiohttp.ClientSession(timeout=WORKER_TIMEOUT)
    tg_app.bot_data["http_session"] = http_session

    await tg_app.initialize()
    await tg_app.start()

    web_app = web.Application()
    web_app["tg_app"] = tg_app
    web_app.router.add_post("/alert", handle_alert)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Gestor HTTP em 0.0.0.0:%s POST /alert", port)

    await tg_app.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram polling ativo. WORKERS=%s", WORKERS)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _sig() -> None:
        logger.info("Parar gestor")
        stop.set()

    try:
        loop.add_signal_handler(signal.SIGINT, _sig)
        loop.add_signal_handler(signal.SIGTERM, _sig)
    except NotImplementedError:
        pass

    await stop.wait()

    await tg_app.updater.stop()
    await tg_app.stop()
    await tg_app.shutdown()
    await http_session.close()
    await runner.cleanup()
    logger.info("Gestor encerrado.")


def main() -> None:
    asyncio.run(run_manager())


if __name__ == "__main__":
    main()
