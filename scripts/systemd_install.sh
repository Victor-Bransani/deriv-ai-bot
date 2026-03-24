#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

if [[ ! -d venv ]]; then
  python3 -m venv venv
fi

venv/bin/pip install --upgrade pip -q
venv/bin/pip install -r requirements.txt

if [[ ! -f .env ]]; then
  if [[ -f env.txt ]]; then
    cp env.txt .env
    echo "Aviso: criado .env a partir de env.txt — confirme segredos na VPS."
  elif [[ -f env.example ]]; then
    cp env.example .env
    echo "ERRO: edite $DIR/.env com DERIV_TOKEN e Telegram antes de iniciar." >&2
    exit 1
  else
    echo "ERRO: falta .env (ou env.txt / env.example)." >&2
    exit 1
  fi
fi

UNIT="/etc/systemd/system/deriv-ai-bot.service"
tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=Deriv AI Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$DIR
EnvironmentFile=$DIR/.env
ExecStart=$DIR/venv/bin/python $DIR/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable deriv-ai-bot
echo "OK: serviço deriv-ai-bot instalado. Inicie com: systemctl start deriv-ai-bot"
