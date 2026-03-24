import { useState, useEffect, useRef, useCallback } from "react";
import type { CandlestickData } from "lightweight-charts";
import type { ConnectionStatus } from "@/components/dashboard/StatusIndicator";

const WS_URL = "wss://ws.binaryws.com/websockets/v3?app_id=1089";

function parseNum(v: unknown): number {
  const n = parseFloat(String(v));
  return Number.isFinite(n) ? n : NaN;
}

function candleToBar(c: Record<string, unknown>): CandlestickData | null {
  const t = parseInt(String(c.epoch), 10);
  if (!Number.isFinite(t)) return null;
  const time = (t > 1e12 ? Math.floor(t / 1000) : t) as CandlestickData["time"];
  const o = parseNum(c.open);
  const h = parseNum(c.high);
  const l = parseNum(c.low);
  const cl = parseNum(c.close);
  if (![o, h, l, cl].every(Number.isFinite)) return null;
  return { time, open: o, high: h, low: l, close: cl };
}

function sortBars(map: Map<number, CandlestickData>): CandlestickData[] {
  return Array.from(map.values()).sort((a, b) => Number(a.time) - Number(b.time));
}

export function useDeriv(symbol: string) {
  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const [statusMessage, setStatusMessage] = useState("");
  const [candles, setCandles] = useState<CandlestickData[]>([]);
  const [currentPrice, setCurrentPrice] = useState<number | null>(null);
  const [previousPrice, setPreviousPrice] = useState<number | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const barsRef = useRef<Map<number, CandlestickData>>(new Map());
  const symbolRef = useRef(symbol);
  const reqIdRef = useRef(1);
  const token = (import.meta.env.VITE_DERIV_TOKEN as string | undefined)?.trim();

  const nextId = useCallback(() => reqIdRef.current++, []);

  const subscribeHistory = useCallback((ws: WebSocket) => {
    ws.send(
      JSON.stringify({
        ticks_history: symbolRef.current,
        end: "latest",
        count: 300,
        style: "candles",
        granularity: 300,
        subscribe: 1,
        req_id: nextId(),
      }),
    );
  }, [nextId]);

  const applyCandles = useCallback((raw: unknown[]) => {
    const map = new Map<number, CandlestickData>();
    for (const row of raw) {
      if (!row || typeof row !== "object") continue;
      const bar = candleToBar(row as Record<string, unknown>);
      if (bar) map.set(Number(bar.time), bar);
    }
    barsRef.current = map;
    const merged = sortBars(map);
    setCandles(merged);
    if (merged.length > 0) {
      setCurrentPrice(merged[merged.length - 1].close);
    }
  }, []);

  const handleOhlc = useCallback((ohlc: Record<string, unknown>) => {
    if (ohlc.symbol && String(ohlc.symbol) !== symbolRef.current) return;
    const ep = ohlc.open_time != null ? ohlc.open_time : ohlc.epoch;
    const bar = candleToBar({
      epoch: ep,
      open: ohlc.open,
      high: ohlc.high,
      low: ohlc.low,
      close: ohlc.close,
    });
    if (!bar) return;
    barsRef.current.set(Number(bar.time), bar);
    setCandles(sortBars(barsRef.current));
    setCurrentPrice((prev) => {
      if (prev !== null) setPreviousPrice(prev);
      return bar.close;
    });
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current) {
      try {
        wsRef.current.close();
      } catch {
        /* ignore */
      }
    }

    barsRef.current = new Map();
    setCandles([]);
    setCurrentPrice(null);
    setPreviousPrice(null);
    setStatus("connecting");
    setStatusMessage("A ligar ao WebSocket…");

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus("connected");
      setStatusMessage(`Ligado · M5 · ${symbolRef.current}`);
      if (token) {
        ws.send(JSON.stringify({ authorize: token, req_id: nextId() }));
      } else {
        setStatusMessage("Sem VITE_DERIV_TOKEN — histórico pode falhar");
        subscribeHistory(ws);
      }
    };

    ws.onmessage = (e) => {
      let msg: Record<string, unknown>;
      try {
        msg = JSON.parse(e.data) as Record<string, unknown>;
      } catch {
        return;
      }

      if (msg.ping !== undefined) {
        ws.send(JSON.stringify({ pong: msg.ping }));
        return;
      }

      if (msg.error) {
        const err = msg.error as { message?: string };
        setStatus("error");
        setStatusMessage(err.message ?? "Erro Deriv");
        return;
      }

      if (msg.authorize && typeof msg.authorize === "object") {
        setStatusMessage(`Autorizado · M5 · ${symbolRef.current}`);
        subscribeHistory(ws);
        return;
      }

      if (Array.isArray(msg.candles)) {
        applyCandles(msg.candles);
        setStatusMessage(`M5 ${symbolRef.current} · ${msg.candles.length} velas · OHLC em tempo real`);
        return;
      }

      if (msg.ohlc && typeof msg.ohlc === "object") {
        handleOhlc(msg.ohlc as Record<string, unknown>);
        return;
      }
    };

    ws.onerror = () => {
      setStatus("error");
      setStatusMessage("Erro de ligação WebSocket");
    };

    ws.onclose = () => {
      if (wsRef.current === ws) {
        setStatus("idle");
        setStatusMessage("Desligado");
      }
    };
  }, [applyCandles, handleOhlc, subscribeHistory, token, nextId]);

  useEffect(() => {
    symbolRef.current = symbol;
    connect();

    return () => {
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch {
          /* ignore */
        }
        wsRef.current = null;
      }
    };
  }, [symbol, connect]);

  return { status, statusMessage, candles, currentPrice, previousPrice };
}
