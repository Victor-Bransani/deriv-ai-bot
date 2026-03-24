import html
import logging

import config
import user_settings
from notifier import format_trade_summary_html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _chat_allowed(update: Update) -> bool:
    if not update.effective_chat:
        return False
    return str(update.effective_chat.id).strip() == str(config.CHAT_ID).strip()


class TelegramInterface:
    def __init__(self, bot_engine=None, notifier=None):
        self.bot_engine = bot_engine
        self.notifier = notifier
        self.app = Application.builder().token(config.TELEGRAM_TOKEN).build()
        self._register_handlers()

    def bind_notifier(self, notifier):
        self.notifier = notifier

    def telegram_sender(self):
        async def _send(text: str, parse_mode: str = ParseMode.HTML):
            await self.app.bot.send_message(
                chat_id=config.CHAT_ID, text=text, parse_mode=parse_mode
            )

        return _send

    def _register_handlers(self):
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("stop", self.cmd_stop))
        self.app.add_handler(CommandHandler("pause", self.cmd_pause))
        self.app.add_handler(CommandHandler("kelly", self.cmd_kelly))
        self.app.add_handler(CommandHandler("bank", self.cmd_bank))
        self.app.add_handler(CallbackQueryHandler(self.handle_callback))

    def _main_keyboard(self):
        keyboard = [
            [
                InlineKeyboardButton("▶️ Iniciar", callback_data="start_bot"),
                InlineKeyboardButton("⏸ Pausar", callback_data="pause_bot"),
            ],
            [
                InlineKeyboardButton("⏹ Parar", callback_data="stop_bot"),
                InlineKeyboardButton("📊 Status", callback_data="status"),
            ],
            [
                InlineKeyboardButton("📐 Kelly", callback_data="kelly:panel"),
                InlineKeyboardButton("💰 Banca TP/SL", callback_data="bank:panel"),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    def _kelly_panel_text(self) -> str:
        s = user_settings.kelly_snapshot()
        nwin = 0
        if self.bot_engine:
            nwin = self.bot_engine.risk.get_stats().get("kelly_trades_in_window", 0)
        ov = "sim" if user_settings.has_any_kelly_override() else "não"
        return (
            f"📐 <b>Kelly e risco</b> (gravado em <code>user_settings.json</code>)\n\n"
            f"• Kelly ativo: <b>{'sim' if s['enabled'] else 'não'}</b>\n"
            f"• Fração Kelly: <b>{s['fraction']:.2f}</b> (ex.: 0,25 = ¼ Kelly)\n"
            f"• Trades mín. p/ Kelly: <b>{s['min_trades']}</b>\n"
            f"• Janela: <b>{s['window']}</b> (trades na memória: {nwin})\n"
            f"• Payoff vitória padrão (b): <b>{s['default_payoff']:.2f}</b>\n"
            f"• Wilson (p conservador): <b>{'sim' if s['use_wilson'] else 'não'}</b>\n"
            f"• Teto % banca/trade: <b>{s['max_bankroll_fraction']:.2%}</b>\n"
            f"• Teto f* bruto: <b>{s['cap_full']:.2f}</b>\n"
            f"• DD suave desde: <b>{s['dd_soft']:.0%}</b> · escala mín. <b>{s['dd_min_scale']:.0%}</b>\n"
            f"• Stake mín.: <b>{s['min_stake']:.2f}</b> USD\n\n"
            f"<i>Override Telegram ativo: {ov} (use Reset para voltar ao .env)</i>"
        )

    def _kelly_markup(self) -> InlineKeyboardMarkup:
        s = user_settings.kelly_snapshot()
        toggle_lbl = "🔴 Desligar Kelly" if s["enabled"] else "🟢 Ligar Kelly"
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(toggle_lbl, callback_data="kelly:toggle")],
                [
                    InlineKeyboardButton("f 10%", callback_data="kelly:frac:0.10"),
                    InlineKeyboardButton("f 25%", callback_data="kelly:frac:0.25"),
                    InlineKeyboardButton("f 50%", callback_data="kelly:frac:0.50"),
                ],
                [
                    InlineKeyboardButton("mín 6", callback_data="kelly:min:6"),
                    InlineKeyboardButton("mín 12", callback_data="kelly:min:12"),
                    InlineKeyboardButton("mín 20", callback_data="kelly:min:20"),
                ],
                [
                    InlineKeyboardButton("jan 40", callback_data="kelly:win:40"),
                    InlineKeyboardButton("jan 80", callback_data="kelly:win:80"),
                    InlineKeyboardButton("jan 120", callback_data="kelly:win:120"),
                ],
                [
                    InlineKeyboardButton("b 0,85", callback_data="kelly:pay:0.85"),
                    InlineKeyboardButton("b 0,90", callback_data="kelly:pay:0.90"),
                    InlineKeyboardButton("b 0,95", callback_data="kelly:pay:0.95"),
                ],
                [
                    InlineKeyboardButton(
                        "Wilson on" + (" ✓" if s["use_wilson"] else ""),
                        callback_data="kelly:wilson:1",
                    ),
                    InlineKeyboardButton(
                        "Wilson off" + ("" if s["use_wilson"] else " ✓"),
                        callback_data="kelly:wilson:0",
                    ),
                ],
                [
                    InlineKeyboardButton("max 3%", callback_data="kelly:maxf:0.03"),
                    InlineKeyboardButton("max 6%", callback_data="kelly:maxf:0.06"),
                    InlineKeyboardButton("max 10%", callback_data="kelly:maxf:0.10"),
                ],
                [
                    InlineKeyboardButton("mín stake 0,35", callback_data="kelly:mnst:0.35"),
                    InlineKeyboardButton("mín stake 1", callback_data="kelly:mnst:1.0"),
                ],
                [
                    InlineKeyboardButton("↩️ Reset (usar .env)", callback_data="kelly:reset"),
                    InlineKeyboardButton("« Menu", callback_data="main:menu"),
                ],
            ]
        )

    async def _reply(self, update: Update, text: str, reply_markup=None):
        em = update.effective_message
        if em:
            await em.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if self.bot_engine:
            self.bot_engine.state["running"] = True
        await self._reply(
            update,
            f"🤖 <b>Deriv AI — trading</b>\n"
            f"✅ <b>Operação ligada.</b> O ciclo analisa o mercado ~a cada 10 s (há cooldown entre trades).\n"
            f"💹 Ativo: {html.escape(str(config.ACTIVE_SYMBOL))}\n"
            f"🧠 Modo: {html.escape(str(config.AI_MODE))}\n\n"
            f"<i><b>Pausar</b> ou <b>Parar</b> interrompe sinais e ordens. <b>Status</b> mostra se está operando.\n"
            f"Use /kelly (Kelly) e /bank (TP/SL % da banca do dia).</i>",
            reply_markup=self._main_keyboard(),
        )

    async def cmd_kelly(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not _chat_allowed(update):
            await self._reply(update, "⛔ Apenas o chat configurado pode alterar o Kelly.")
            return
        await self._reply(
            update,
            self._kelly_panel_text(),
            reply_markup=self._kelly_markup(),
        )

    def _bank_panel_text(self) -> str:
        b = user_settings.bank_snapshot()
        dop = 0.0
        if self.bot_engine:
            dop = self.bot_engine.risk.day_start_balance
        tp, sl = b["tp_daily_pct"], b["sl_daily_pct"]
        tp_s = f"{tp:.2%}" if tp > 0 else "off"
        sl_s = f"{sl:.2%}" if sl > 0 else "off"
        ov = "sim" if user_settings.has_any_bank_override() else "não"
        return (
            f"💰 <b>Banca — TP / SL diário</b>\n\n"
            f"Limites em <b>percentual do saldo de referência do dia</b> "
            f"(primeiro saldo lido após virar o dia ou ao iniciar).\n\n"
            f"• <b>TP</b> (take profit): pausa ao atingir lucro do dia ≥ este % da ref.\n"
            f"• <b>SL</b> (stop loss): pausa se PnL do dia ≤ −este % da ref.\n\n"
            f"TP atual: <b>{tp_s}</b>\n"
            f"SL atual: <b>{sl_s}</b>\n"
            f"Ref. abertura hoje: <b>{dop:.2f}</b> USD\n\n"
            f"<i>Overrides Telegram: {ov} · Reset volta ao .env</i>"
        )

    def _bank_markup(self) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("TP 3%", callback_data="bank:tp:0.03"),
                    InlineKeyboardButton("TP 5%", callback_data="bank:tp:0.05"),
                    InlineKeyboardButton("TP 8%", callback_data="bank:tp:0.08"),
                    InlineKeyboardButton("TP off", callback_data="bank:tp:0"),
                ],
                [
                    InlineKeyboardButton("SL 3%", callback_data="bank:sl:0.03"),
                    InlineKeyboardButton("SL 5%", callback_data="bank:sl:0.05"),
                    InlineKeyboardButton("SL 10%", callback_data="bank:sl:0.10"),
                    InlineKeyboardButton("SL off", callback_data="bank:sl:0"),
                ],
                [
                    InlineKeyboardButton("↩️ Reset banca", callback_data="bank:reset"),
                    InlineKeyboardButton("« Menu", callback_data="main:menu"),
                ],
            ]
        )

    async def cmd_bank(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not _chat_allowed(update):
            await self._reply(update, "⛔ Apenas o chat configurado pode alterar isto.")
            return
        await self._reply(
            update,
            self._bank_panel_text(),
            reply_markup=self._bank_markup(),
        )

    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if self.bot_engine:
            s = self.bot_engine.state
            op = "sim" if s["running"] else "não"
            ks = self.bot_engine.risk.get_stats()
            kw = ks.get("kelly_trades_in_window", 0)
            ke = ks.get("kelly_effective") or user_settings.kelly_snapshot()
            kwin = ke.get("window", config.KELLY_WINDOW)
            km = ks.get("kelly_last") or {}
            kelly_line = (
                f"📐 Kelly: janela <b>{kw}</b>/{kwin} trades · "
                f"último modo <code>{html.escape(str(km.get('mode', '-')))}</code>"
            )
            if km.get("p_used") is not None:
                kelly_line += f" · p≈{km.get('p_used')} b≈{km.get('b_hat')}"
            be = ks.get("bank_effective") or user_settings.bank_snapshot()
            tpv, slv = be["tp_daily_pct"], be["sl_daily_pct"]
            tp_txt = f"{tpv:.2%}" if tpv > 0 else "off"
            sl_txt = f"{slv:.2%}" if slv > 0 else "off"
            bank_line = (
                f"💰 TP/SL dia: TP <b>{tp_txt}</b> · SL <b>{sl_txt}</b> "
                f"(ref. {ks.get('day_open_balance', 0):.2f} USD)"
            )
            cl = ks.get("consecutive_loss", 0)
            mx = ks.get("max_consecutive_before_pause", 3)
            if ks.get("paused"):
                risk_line = (
                    f"\n🛑 <b>Risco — PAUSADO</b>\n"
                    f"{html.escape(str(ks.get('pause_reason') or 'Motivo não definido'))}"
                )
            else:
                risk_line = (
                    f"\n📉 Perdas seguidas: <b>{cl}</b>/{mx} "
                    f"(ao atingir {mx}, entra pausa até o próximo dia)"
                )
            msg = (
                f"📊 <b>Status do bot</b>\n"
                f"▶️ Buscando sinais / operando: <b>{op}</b>\n"
                f"💰 Saldo: {s['balance']:.2f} USD\n"
                f"📈 PnL do dia: {s['daily_pnl']:.2f} USD\n"
                f"🎯 Último sinal: {html.escape(str(s['last_signal']))}\n"
                f"🔥 Confiança: {s['last_confidence']:.1%}\n"
                f"💹 Ativo: {html.escape(str(s['symbol']))}\n"
                f"🧠 Modo IA: {html.escape(str(s['ai_mode']))}"
                f"{risk_line}\n"
                f"{kelly_line}\n"
                f"{bank_line}\n\n"
                f"<i>/kelly · /bank</i>"
            )
        else:
            msg = "📊 Bot online."
        await self._reply(update, msg, reply_markup=self._main_keyboard())

    async def cmd_stop(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if self.bot_engine:
            self.bot_engine.state["running"] = False
        await self._reply(
            update,
            "⏹ <b>Bot parado.</b> Nenhuma nova análise de trade será executada.",
            reply_markup=self._main_keyboard(),
        )

    async def cmd_pause(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if self.bot_engine:
            self.bot_engine.state["running"] = False
        await self._reply(
            update,
            "⏸ <b>Pausado.</b> Use <b>Iniciar</b> ou /start para voltar a operar.",
            reply_markup=self._main_keyboard(),
        )

    async def _apply_kelly_action(self, data: str) -> None:
        if data == "kelly:toggle":
            cur = user_settings.effective_bool("kelly_enabled", config.KELLY_ENABLED)
            user_settings.set_value("kelly_enabled", not cur)
        elif data.startswith("kelly:frac:"):
            user_settings.set_value("kelly_fraction", float(data.split(":")[2]))
        elif data.startswith("kelly:min:"):
            user_settings.set_value("kelly_min_trades", int(data.split(":")[2]))
        elif data.startswith("kelly:win:"):
            user_settings.set_value("kelly_window", int(data.split(":")[2]))
        elif data.startswith("kelly:pay:"):
            user_settings.set_value("kelly_default_win_payoff", float(data.split(":")[2]))
        elif data.startswith("kelly:wilson:"):
            user_settings.set_value("kelly_use_wilson", data.endswith(":1"))
        elif data.startswith("kelly:maxf:"):
            user_settings.set_value("kelly_max_bankroll_fraction", float(data.split(":")[2]))
        elif data.startswith("kelly:mnst:"):
            user_settings.set_value("min_stake", float(data.split(":")[2]))
        elif data == "kelly:reset":
            user_settings.clear_kelly_keys()

    async def _apply_bank_action(self, data: str) -> None:
        if data.startswith("bank:tp:"):
            user_settings.set_value("tp_daily_pct", float(data.split(":")[2]))
        elif data.startswith("bank:sl:"):
            user_settings.set_value("sl_daily_pct", float(data.split(":")[2]))
        elif data == "bank:reset":
            user_settings.clear_bank_keys()

    async def handle_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data or ""

        if data == "main:menu":
            try:
                await query.edit_message_text(
                    "🤖 <b>Menu</b> — /kelly · /bank",
                    parse_mode=ParseMode.HTML,
                    reply_markup=self._main_keyboard(),
                )
            except Exception:
                await self._reply(
                    update,
                    "🤖 <b>Menu</b>",
                    reply_markup=self._main_keyboard(),
                )
            return

        if data.startswith("bank:"):
            if not _chat_allowed(update):
                await query.edit_message_text(
                    "⛔ Apenas o chat configurado pode alterar isto.",
                    parse_mode=ParseMode.HTML,
                )
                return
            if data != "bank:panel":
                await self._apply_bank_action(data)
            try:
                await query.edit_message_text(
                    self._bank_panel_text(),
                    parse_mode=ParseMode.HTML,
                    reply_markup=self._bank_markup(),
                )
            except Exception:
                await self._reply(
                    update,
                    self._bank_panel_text(),
                    reply_markup=self._bank_markup(),
                )
            return

        if data.startswith("kelly:"):
            if not _chat_allowed(update):
                await query.edit_message_text(
                    "⛔ Apenas o chat configurado pode alterar isto.",
                    parse_mode=ParseMode.HTML,
                )
                return
            if data == "kelly:panel":
                pass
            else:
                await self._apply_kelly_action(data)
                if self.bot_engine:
                    self.bot_engine.risk._ensure_kelly_window()
            try:
                await query.edit_message_text(
                    self._kelly_panel_text(),
                    parse_mode=ParseMode.HTML,
                    reply_markup=self._kelly_markup(),
                )
            except Exception:
                await self._reply(
                    update,
                    self._kelly_panel_text(),
                    reply_markup=self._kelly_markup(),
                )
            return

        if not self.bot_engine:
            return
        kb = self._main_keyboard()
        if data == "start_bot":
            self.bot_engine.state["running"] = True
            try:
                await query.edit_message_text(
                    "▶️ <b>Operação ligada.</b> Buscando sinais no próximo ciclo (~10 s).",
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb,
                )
            except Exception:
                await self._reply(
                    update,
                    "▶️ <b>Operação ligada.</b>",
                    reply_markup=kb,
                )
        elif data == "stop_bot":
            self.bot_engine.state["running"] = False
            try:
                await query.edit_message_text(
                    "⏹ <b>Parado.</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb,
                )
            except Exception:
                await self._reply(update, "⏹ <b>Parado.</b>", reply_markup=kb)
        elif data == "pause_bot":
            self.bot_engine.state["running"] = False
            try:
                await query.edit_message_text(
                    "⏸ <b>Pausado.</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb,
                )
            except Exception:
                await self._reply(update, "⏸ <b>Pausado.</b>", reply_markup=kb)
        elif data == "status":
            await self.cmd_status(update, ctx)

    async def send_alert(self, trade_info: dict):
        if self.notifier:
            await self.notifier.trade_signal(trade_info)
            return
        sym = html.escape(str(trade_info["symbol"]))
        mode = html.escape(str(trade_info["mode"]))
        typ = html.escape(str(trade_info["type"]))
        if trade_info.get("won") is None:
            reason = html.escape(str(trade_info["reason"]))
            msg = (
                f"🔔 <b>Sinal {typ}</b>\n"
                f"💹 {sym} | 🧠 {mode}\n"
                f"💵 Entrada: {trade_info['stake']:.2f} USD\n"
                f"🔥 Confiança: {trade_info['confidence']:.1%}\n"
                f"📝 Motivo: {reason}\n"
                f"🕐 {html.escape(str(trade_info['time']))}"
                f"{format_trade_summary_html(trade_info)}"
            )
        else:
            emoji = "✅" if trade_info["won"] else "❌"
            msg = (
                f"{emoji} <b>Resultado</b>\n"
                f"💹 {sym} | {typ}\n"
                f"💰 PnL: {trade_info.get('pnl', 0):.2f} USD\n"
                f"🕐 {html.escape(str(trade_info['time']))}"
                f"{format_trade_summary_html(trade_info)}"
            )
        await self.app.bot.send_message(
            chat_id=config.CHAT_ID, text=msg, parse_mode=ParseMode.HTML
        )
