import os
import logging
from pathlib import Path

from dotenv import load_dotenv

_root = Path(__file__).resolve().parent
# VPS: coloque variáveis em .env na pasta do projeto (ou export no systemd/Docker).
load_dotenv(_root / ".env")
# Desenvolvimento local: env.txt preenche só o que ainda não estiver definido.
load_dotenv(_root / "env.txt", override=False)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")

# ID numérico da aplicação em https://app.deriv.com / API settings (não use token ou string alfanumérica aqui).
DERIV_APP_ID = os.getenv("DERIV_APP_ID", "1089")
DERIV_TOKEN = os.getenv("DERIV_TOKEN")
DERIV_DEMO = os.getenv("DERIV_DEMO", "true").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# WebSocket / VPS
WS_PING_INTERVAL = int(os.getenv("WS_PING_INTERVAL", "20"))
WS_PING_TIMEOUT = int(os.getenv("WS_PING_TIMEOUT", "20"))
WS_REQUEST_TIMEOUT = float(os.getenv("WS_REQUEST_TIMEOUT", "60"))
WS_CONTRACT_SUBSCRIBE_TIMEOUT = float(os.getenv("WS_CONTRACT_SUBSCRIBE_TIMEOUT", "30"))
WS_RECONNECT_INITIAL_DELAY = float(os.getenv("WS_RECONNECT_INITIAL_DELAY", "2"))
WS_RECONNECT_MAX_DELAY = float(os.getenv("WS_RECONNECT_MAX_DELAY", "60"))
CONTRACT_RESULT_MAX_WAIT = int(os.getenv("CONTRACT_RESULT_MAX_WAIT", "7200"))
# Trades “fantasma”: sem evento terminal no WS dentro deste tempo → libertar estado no bot
GHOST_TRADE_TIMEOUT_SEC = float(os.getenv("GHOST_TRADE_TIMEOUT_SEC", "3600"))

# Opcional: URL POST JSON para alertas (Discord/n8n/etc.)
ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "").strip()

# Operário → Gestor central (telegram_manager.py) — alertas para o Telegram
MANAGER_WEBHOOK_URL = os.getenv(
    "MANAGER_WEBHOOK_URL", "http://localhost:8000/alert"
).strip()

# Na VPS: true = já busca sinais sem precisar apertar Iniciar no Telegram
AUTO_START_TRADING = os.getenv("AUTO_START_TRADING", "false").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

ACTIVE_SYMBOL = "V75"
STAKE_AMOUNT = 1.0
# Teto de liquidez/segurança (1% da banca até aqui; ex.: 50k × 1% = 500)
MAX_STAKE = float(os.getenv("MAX_STAKE", "500.0"))
CURRENCY = os.getenv("CURRENCY", "USD").strip().upper() or "USD"

# Multiplicadores (MULTUP / MULTDOWN) — sem duração; TP/SL em valor monetário sobre a stake
MULTIPLIER = int(os.getenv("MULTIPLIER", "100"))
TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "1.50"))  # ex.: 1.50 = +150% do stake
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "0.50"))  # ex.: 0.50 = 50% do stake
MAX_STAKE_PCT = float(os.getenv("MAX_STAKE_PCT", "0.01"))  # 1% da banca (mín. 1 USD no risk_manager)

MAX_DAILY_LOSS = 0.10
MAX_DAILY_TRADES = 20   # máximo de trades por dia
RISK_PER_TRADE = 0.02

AI_MODE = "AUTO"
MIN_CONFIDENCE = 0.65
# Granularidades Deriv (segundos): M5=300, M15=900
CANDLE_GRANULARITY_M5 = 300
CANDLE_GRANULARITY_M15 = 900
OBI_THRESHOLD = 0.55
MAX_CONSECUTIVE_LOSS = 5
TRADE_COOLDOWN = 90     # segundos entre tentativas de trade

# --- Kelly (critério de Kelly + fração; maximiza crescimento log esperado no modelo binário) ---
KELLY_ENABLED = os.getenv("KELLY_ENABLED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
# Fração do Kelly completo (ex.: 0.25 = "quarto de Kelly", comum na prática)
KELLY_FRACTION = float(os.getenv("KELLY_FRACTION", "0.25"))
# Janela deslizante de trades fechados para estimar p e b
KELLY_WINDOW = int(os.getenv("KELLY_WINDOW", "80"))
# Antes disto, usa RISK_PER_TRADE (aquecimento)
KELLY_MIN_TRADES = int(os.getenv("KELLY_MIN_TRADES", "12"))
# Lucro por 1 USD de stake em vitória (modelo binário Kelly); multiplicadores ~1.5 com TP +150% da stake
KELLY_DEFAULT_WIN_PAYOFF = float(os.getenv("KELLY_DEFAULT_WIN_PAYOFF", "1.5"))
# p conservador: limite inferior Wilson vs média Beta
KELLY_USE_WILSON = os.getenv("KELLY_USE_WILSON", "true").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
# Prior Beta para p (pseudo vitórias/derrotas)
KELLY_PRIOR_WINS = float(os.getenv("KELLY_PRIOR_WINS", "1.0"))
KELLY_PRIOR_LOSSES = float(os.getenv("KELLY_PRIOR_LOSSES", "1.0"))
# Teto no f* bruto da fórmula antes de aplicar KELLY_FRACTION (evita explosão quando b é pequeno)
KELLY_CAP_FULL_FRACTION = float(os.getenv("KELLY_CAP_FULL_FRACTION", "0.35"))
# Teto final: fração máxima da banca por trade, após Kelly
KELLY_MAX_BANKROLL_FRACTION = float(os.getenv("KELLY_MAX_BANKROLL_FRACTION", "0.06"))
# Drawdown desde pico: a partir desta fração (0–1), reduz agressividade
KELLY_DD_SOFT_START = float(os.getenv("KELLY_DD_SOFT_START", "0.12"))
# No drawdown máximo (100%), escala o f até este mínimo (0–1)
KELLY_DD_MIN_SCALE = float(os.getenv("KELLY_DD_MIN_SCALE", "0.35"))
MIN_STAKE = float(os.getenv("MIN_STAKE", "0.35"))

# TP/SL diário em % da banca na abertura do dia (0 = desligado). Ex.: 0.05 = 5%
TP_DAILY_PCT = float(os.getenv("TP_DAILY_PCT", "0"))
SL_DAILY_PCT = float(os.getenv("SL_DAILY_PCT", "0"))

# Dados para ML / auditoria
DATA_DIR = Path(os.getenv("DATA_DIR", str(_root / "data")))
TICK_CSV_ENABLED = os.getenv("TICK_CSV_ENABLED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
CYCLE_CSV_ENABLED = os.getenv("CYCLE_CSV_ENABLED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
TICK_QUEUE_MAX = int(os.getenv("TICK_QUEUE_MAX", "100000"))

# Logging: consola + opcional ficheiro rotativo
LOG_LEVEL = getattr(
    logging,
    os.getenv("LOG_LEVEL", "INFO").strip().upper(),
    logging.INFO,
)
BOT_LOG_FILE = (os.getenv("BOT_LOG_FILE", "") or "").strip()
BOT_LOG_MAX_BYTES = int(os.getenv("BOT_LOG_MAX_BYTES", str(10 * 1024 * 1024)))
BOT_LOG_BACKUP_COUNT = int(os.getenv("BOT_LOG_BACKUP_COUNT", "5"))
# Intervalo (s) para lembrar que o trading automático está desligado
IDLE_TRADING_LOG_INTERVAL_SEC = float(os.getenv("IDLE_TRADING_LOG_INTERVAL_SEC", "300"))
