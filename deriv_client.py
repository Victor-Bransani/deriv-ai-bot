import asyncio
import json
import logging
import random
from typing import Any, Dict, List, Optional, Tuple

import websockets
from websockets.exceptions import ConnectionClosed

import config

logger = logging.getLogger(__name__)


class DerivClientError(Exception):
    """Erro da API Deriv; `raw_message` é a mensagem WebSocket completa quando disponível."""

    def __init__(
        self, message: str, *, raw_message: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(message)
        self.raw_message = raw_message


class DerivClient:
    """Cliente WebSocket Deriv com ping/pong, req_id, subscrições e reconexão."""

    WS_URL = "wss://ws.binaryws.com/websockets/v3?app_id={}"

    def __init__(self, auth_symbol: Optional[str] = None) -> None:
        # Símbolo UI ou Deriv usado só para escolher DERIV_TOKEN_V## vs DERIV_TOKEN no authorize.
        self._auth_symbol = (auth_symbol or config.ACTIVE_SYMBOL or "V75").strip()
        self._ws: Optional[Any] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._req_id = 1
        self._pending: Dict[int, asyncio.Future] = {}
        self._lock = asyncio.Lock()
        self._closing = False
        self._contract_queues: Dict[int, asyncio.Queue] = {}
        self.balance = 0.0
        self.authorized = False
        self._tick_queue: Optional[asyncio.Queue] = None
        self._tick_stream_symbol: Optional[str] = None
        self._tick_stream_sub_id: Optional[str] = None

    def _next_req_id(self) -> int:
        rid = self._req_id
        self._req_id += 1
        return rid

    async def connect(self) -> None:
        await self._open_and_authorize()

    async def _open_and_authorize(self) -> None:
        self._closing = False
        app_id = str(config.DERIV_APP_ID).strip()
        if not app_id.isdigit():
            raise DerivClientError(
                "DERIV_APP_ID deve ser numérico (ex.: painel Deriv → Applications). "
                "URLs ws usam apenas o ID numérico."
            )
        url = self.WS_URL.format(app_id)
        logger.info("Conectando WebSocket Deriv (app_id=%s)...", app_id)
        self._ws = await websockets.connect(
            url,
            ping_interval=config.WS_PING_INTERVAL,
            ping_timeout=config.WS_PING_TIMEOUT,
            close_timeout=10,
            max_size=2**22,
        )
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        self._reader_task = asyncio.create_task(self._reader_loop(), name="deriv-ws-reader")
        await self.authorize()
        await self._resubscribe_tick_stream_after_auth()

    async def ensure_connected(self) -> None:
        if self._ws and not self._ws.closed and self.authorized:
            return
        delay = config.WS_RECONNECT_INITIAL_DELAY
        attempt = 0
        while not self._closing:
            try:
                await self._open_and_authorize()
                return
            except Exception as e:
                attempt += 1
                logger.warning("Reconexão falhou (%s): %s — retry em %.1fs", attempt, e, delay)
                await asyncio.sleep(delay + random.uniform(0, 0.5 * delay))
                delay = min(delay * 2, config.WS_RECONNECT_MAX_DELAY)

    async def _reader_loop(self) -> None:
        assert self._ws is not None
        try:
            while not self._closing:
                try:
                    raw = await self._ws.recv()
                except ConnectionClosed as e:
                    logger.warning("WebSocket fechado: %s", e)
                    self._fail_all_pending(DerivClientError("WebSocket fechado"))
                    self.authorized = False
                    break
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("JSON inválido do servidor: %s", raw[:200])
                    continue
                await self._dispatch_message(msg)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Reader loop error: %s", e)
            self._fail_all_pending(e)

    def _fail_all_pending(self, err: BaseException) -> None:
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(err)
        self._pending.clear()

    async def _dispatch_message(self, msg: Dict[str, Any]) -> None:
        if "ping" in msg:
            await self._send_raw({"pong": msg["ping"]})
            return

        if "error" in msg:
            err = msg["error"]
            detail = err.get("message", err) if isinstance(err, dict) else err
            rid = msg.get("req_id")
            if rid is not None and rid in self._pending:
                fut = self._pending.pop(rid)
                if not fut.done():
                    fut.set_exception(
                        DerivClientError(str(detail), raw_message=dict(msg))
                    )
            # Pode repetir com o try/except do proposal/buy; garante visibilidade em todos os pedidos.
            logger.error("Deriv WS error (JSON completo): %s", json.dumps(msg, default=str))
            return

        if "tick" in msg:
            if self._tick_queue is not None:
                try:
                    self._tick_queue.put_nowait(msg)
                except asyncio.QueueFull:
                    logger.warning(
                        "Fila de ticks cheia — descartando (TICK_QUEUE_MAX / consumo CSV)"
                    )
            return

        poc = msg.get("proposal_open_contract")
        if isinstance(poc, dict):
            cid = poc.get("contract_id")
            if cid is not None:
                q = self._contract_queues.get(int(cid))
                if q is not None:
                    try:
                        q.put_nowait(msg)
                    except asyncio.QueueFull:
                        pass

        rid = msg.get("req_id")
        if rid is not None and rid in self._pending:
            fut = self._pending.pop(rid)
            if not fut.done():
                fut.set_result(msg)

    async def _send_raw(self, data: Dict[str, Any]) -> None:
        if not self._ws or self._ws.closed:
            raise DerivClientError("WebSocket não conectado")
        await self._ws.send(json.dumps(data))

    async def _send_request(self, payload: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:
        timeout = timeout if timeout is not None else config.WS_REQUEST_TIMEOUT
        async with self._lock:
            rid = self._next_req_id()
            body = {**payload, "req_id": rid}
            loop = asyncio.get_running_loop()
            fut: asyncio.Future = loop.create_future()
            self._pending[rid] = fut
            await self._send_raw(body)
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(rid, None)
            raise DerivClientError(f"Timeout aguardando req_id={rid}") from None
        except Exception:
            self._pending.pop(rid, None)
            raise

    async def request(self, payload: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:
        await self.ensure_connected()
        return await self._send_request(payload, timeout=timeout)

    async def authorize(self) -> None:
        token = config.get_deriv_token_for_symbol(self._auth_symbol)
        if not token:
            raise DerivClientError(
                f"Token Deriv ausente para ativo {self._auth_symbol!r} "
                "(defina DERIV_TOKEN ou o DERIV_TOKEN_V## correspondente)"
            )
        master = (config.DERIV_TOKEN or "").strip()
        vol_key = config.normalized_volatility_symbol(self._auth_symbol)
        using = "específico" if token != master else "principal (DERIV_TOKEN)"
        logger.info(
            "Deriv authorize: ativo=%s vol_key=%s origem=%s",
            self._auth_symbol,
            vol_key or "—",
            using,
        )
        try:
            resp = await self._send_request({"authorize": token})
        except DerivClientError as e:
            logger.error(
                "Falha authorize Deriv (ativo=%s, origem=%s): %s",
                self._auth_symbol,
                using,
                e,
            )
            raise
        if "authorize" not in resp:
            raise DerivClientError(f"Falha authorize: {resp}")
        self.authorized = True
        self.balance = float(resp["authorize"].get("balance", 0))
        logger.info("Deriv autorizado. Saldo: %.2f", self.balance)

    def set_tick_queue(self, queue: Optional[asyncio.Queue]) -> None:
        self._tick_queue = queue

    async def _forget_tick_stream(self) -> None:
        if not self._tick_stream_sub_id:
            return
        sid = self._tick_stream_sub_id
        self._tick_stream_sub_id = None
        try:
            if self._ws and not self._ws.closed and self.authorized:
                await self._send_request({"forget": sid}, timeout=5)
        except Exception as e:
            logger.warning("forget tick stream %s: %s", sid, e)

    async def _resubscribe_tick_stream_after_auth(self) -> None:
        if not self._tick_stream_symbol or self._tick_queue is None:
            return
        try:
            resp = await self.request(
                {"ticks": self._tick_stream_symbol, "subscribe": 1}
            )
            sub = resp.get("subscription") or {}
            self._tick_stream_sub_id = sub.get("id")
            logger.info(
                "Stream de ticks: %s (subscription id=%s)",
                self._tick_stream_symbol,
                self._tick_stream_sub_id,
            )
        except Exception as e:
            logger.warning(
                "Re-subscrição de ticks falhou (%s): %s",
                self._tick_stream_symbol,
                e,
            )

    async def subscribe_tick_stream(self, symbol: str) -> None:
        """Subscrição contínua de ticks para gravação / ML (re-subscreve após reconexão)."""
        await self.ensure_connected()
        if self._tick_queue is None:
            raise DerivClientError(
                "Defina a fila com set_tick_queue() antes de subscribe_tick_stream()"
            )
        await self._forget_tick_stream()
        self._tick_stream_symbol = symbol
        await self._resubscribe_tick_stream_after_auth()

    async def get_candles(self, symbol: str, count: int = 200, tf: int = 60) -> List[Dict[str, Any]]:
        resp = await self.request(
            {
                "ticks_history": symbol,
                "count": count,
                "end": "latest",
                "granularity": tf,
                "style": "candles",
            }
        )
        return resp.get("candles") or []

    async def get_balance(self) -> float:
        resp = await self.request({"balance": 1})
        bal = float(resp.get("balance", {}).get("balance", 0))
        self.balance = bal
        return bal

    @staticmethod
    def _multiplier_limit_order_numeric(stake: float) -> Dict[str, float]:
        st = float(stake)
        return {
            "take_profit": round(st * config.TAKE_PROFIT_PCT, 2),
            "stop_loss": round(st * config.STOP_LOSS_PCT, 2),
        }

    async def buy_multiplier_execute(
        self, contract_type: str, stake: float, symbol: str
    ) -> Optional[Tuple[int, float]]:
        """
        Envia proposal + buy para MULTUP/MULTDOWN (multiplicador).
        Sem duration, sem cancellation fee; apenas TP/SL em limit_order (valores numéricos).
        """
        stake_amt = round(float(stake), 2)
        proposal_payload: Dict[str, Any] = {
            "proposal": 1,
            "amount": stake_amt,
            "basis": "stake",
            "contract_type": contract_type,
            "currency": config.CURRENCY,
            "symbol": symbol,
            "multiplier": int(config.MULTIPLIER),
            "limit_order": self._multiplier_limit_order_numeric(stake_amt),
        }

        try:
            proposal = await self.request(proposal_payload)
        except DerivClientError as e:
            if e.raw_message is not None:
                logger.error(
                    "proposal multiplicador — objeto JSON completo: %s",
                    json.dumps(e.raw_message, default=str),
                )
            else:
                logger.error("proposal multiplicador falhou: %s", e)
            return None

        if "proposal" not in proposal:
            logger.error(
                "proposal multiplicador — resposta sem chave proposal: %s",
                json.dumps(proposal, default=str),
            )
            return None
        proposal_id = proposal["proposal"]["id"]

        buy_payload: Dict[str, Any] = {
            "buy": proposal_id,
            "price": stake_amt,
        }
        try:
            buy_resp = await self.request(buy_payload)
        except DerivClientError as e:
            if e.raw_message is not None:
                logger.error(
                    "buy multiplicador — objeto JSON completo: %s",
                    json.dumps(e.raw_message, default=str),
                )
            else:
                logger.error("buy multiplicador falhou: %s", e)
            return None

        if "buy" not in buy_resp:
            logger.error(
                "buy multiplicador — resposta sem chave buy: %s",
                json.dumps(buy_resp, default=str),
            )
            return None

        contract_id = int(buy_resp["buy"]["contract_id"])
        buy_price = float(buy_resp["buy"]["buy_price"])
        logger.info(
            "Multiplicador comprado id=%s tipo=%s mult=%s buy_price=%.2f",
            contract_id,
            contract_type,
            config.MULTIPLIER,
            buy_price,
        )
        return contract_id, buy_price

    async def buy_contract(
        self, contract_type: str, stake: float, symbol: str
    ) -> Optional[Dict[str, Any]]:
        """Proposal + buy + espera até encerramento (TP/SL ou venda)."""
        pair = await self.buy_multiplier_execute(contract_type, stake, symbol)
        if not pair:
            return None
        contract_id, buy_price = pair
        return await self.wait_for_result(contract_id, buy_price)

    async def wait_for_result(self, contract_id: int, buy_price: float) -> Dict[str, Any]:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._contract_queues[contract_id] = q
        sub_id: Optional[str] = None
        try:
            ack = await self.request(
                {
                    "proposal_open_contract": 1,
                    "contract_id": contract_id,
                    "subscribe": 1,
                },
                timeout=config.WS_CONTRACT_SUBSCRIBE_TIMEOUT,
            )
            sub = ack.get("subscription") or {}
            sub_id = sub.get("id")
            done = self._terminal_from_message(ack, contract_id, buy_price)
            if done is not None:
                return done

            max_wait = int(config.CONTRACT_RESULT_MAX_WAIT)
            for _ in range(max_wait):
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                done = self._terminal_from_message(msg, contract_id, buy_price)
                if done is not None:
                    return done

            logger.warning("Timeout resultado contrato %s — profit_table", contract_id)
            return await self.get_contract_result(contract_id, buy_price)
        finally:
            self._contract_queues.pop(contract_id, None)
            if sub_id:
                try:
                    await self._send_request({"forget": sub_id}, timeout=10)
                except Exception as e:
                    logger.warning("forget subscription %s: %s", sub_id, e)

    def _terminal_from_message(
        self, msg: Dict[str, Any], contract_id: int, buy_price: float
    ) -> Optional[Dict[str, Any]]:
        poc = msg.get("proposal_open_contract")
        if not isinstance(poc, dict):
            return None
        if int(poc.get("contract_id", 0)) != contract_id:
            return None
        status = poc.get("status", "")
        if status == "sold" or poc.get("is_expired", 0) == 1:
            profit = float(poc.get("profit", 0))
            sell_price = float(poc.get("sell_price", 0))
            won = profit > 0
            logger.info("Contrato %s encerrado won=%s pnl=%.2f", contract_id, won, profit)
            return {
                "contract_id": contract_id,
                "profit": profit,
                "sell_price": sell_price,
                "buy_price": buy_price,
                "won": won,
            }
        return None

    async def get_contract_result(self, contract_id: int, buy_price: float) -> Dict[str, Any]:
        resp = await self.request(
            {"profit_table": 1, "contract_id": contract_id, "description": 1},
            timeout=30,
        )
        contracts = resp.get("profit_table", {}).get("transactions") or []
        if contracts:
            c = contracts[0]
            profit = float(c.get("sell_price", 0)) - float(c.get("buy_price", buy_price))
            return {
                "contract_id": contract_id,
                "profit": profit,
                "buy_price": buy_price,
                "won": profit > 0,
                "settled": True,
            }
        return {
            "contract_id": contract_id,
            "profit": 0.0,
            "buy_price": buy_price,
            "won": False,
            "settled": False,
        }

    async def disconnect(self) -> None:
        self._closing = True
        await self._forget_tick_stream()
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        self._reader_task = None
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        self.authorized = False
