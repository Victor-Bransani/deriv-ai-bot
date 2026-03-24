import asyncio
import json
import logging
import random
from typing import Any, Dict, List, Optional

import websockets
from websockets.exceptions import ConnectionClosed

import config

logger = logging.getLogger(__name__)


class DerivClientError(Exception):
    pass


class DerivClient:
    """Cliente WebSocket Deriv com ping/pong, req_id, subscrições e reconexão."""

    WS_URL = "wss://ws.binaryws.com/websockets/v3?app_id={}"

    def __init__(self) -> None:
        self._ws: Optional[Any] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._req_id = 1
        self._pending: Dict[int, asyncio.Future] = {}
        self._lock = asyncio.Lock()
        self._closing = False
        self._contract_queues: Dict[int, asyncio.Queue] = {}
        self.balance = 0.0
        self.authorized = False

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
                    fut.set_exception(DerivClientError(str(detail)))
            logger.warning("Deriv error: %s", detail)
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
        if not config.DERIV_TOKEN:
            raise DerivClientError("DERIV_TOKEN não configurado")
        resp = await self._send_request({"authorize": config.DERIV_TOKEN})
        if "authorize" not in resp:
            raise DerivClientError(f"Falha authorize: {resp}")
        self.authorized = True
        self.balance = float(resp["authorize"].get("balance", 0))
        logger.info("Deriv autorizado. Saldo: %.2f", self.balance)

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

    async def buy_contract(
        self, contract_type: str, stake: float, duration: int, symbol: str
    ) -> Optional[Dict[str, Any]]:
        proposal = await self.request(
            {
                "proposal": 1,
                "amount": str(stake),
                "basis": "stake",
                "contract_type": contract_type,
                "currency": "USD",
                "duration": duration,
                "duration_unit": config.DURATION_UNIT,
                "symbol": symbol,
            }
        )
        if "proposal" not in proposal:
            logger.error("proposal error: %s", proposal)
            return None
        proposal_id = proposal["proposal"]["id"]

        buy_resp = await self.request({"buy": proposal_id, "price": str(stake)})
        if "buy" not in buy_resp:
            logger.error("buy error: %s", buy_resp)
            return None

        contract_id = int(buy_resp["buy"]["contract_id"])
        buy_price = float(buy_resp["buy"]["buy_price"])
        logger.info("Contrato comprado id=%s stake=%.2f", contract_id, buy_price)

        result = await self.wait_for_result(contract_id, buy_price)
        return result

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
            }
        return {"contract_id": contract_id, "profit": 0.0, "buy_price": buy_price, "won": False}

    async def disconnect(self) -> None:
        self._closing = True
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
