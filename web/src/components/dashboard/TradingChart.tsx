import { useEffect, useRef, useCallback } from "react";
import {
  createChart,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type LineData,
  type SeriesMarker,
  type Time,
  ColorType,
  CandlestickSeries,
  LineSeries,
} from "lightweight-charts";
import AILogsPanel from "@/components/dashboard/AILogsPanel";

const EMA_PERIOD = 20;
/** Multiplicador EMA: 2 / (period + 1) */
const EMA_MULT = 2 / (EMA_PERIOD + 1);

function computeEmaLineData(bars: CandlestickData[]): LineData[] {
  if (bars.length < EMA_PERIOD) return [];
  let ema = 0;
  for (let i = 0; i < EMA_PERIOD; i++) ema += bars[i].close;
  ema /= EMA_PERIOD;
  const out: LineData[] = [{ time: bars[EMA_PERIOD - 1].time, value: ema }];
  for (let i = EMA_PERIOD; i < bars.length; i++) {
    ema = bars[i].close * EMA_MULT + ema * (1 - EMA_MULT);
    out.push({ time: bars[i].time, value: ema });
  }
  return out;
}

interface TradeMarkerRow {
  time: Time;
  position: SeriesMarker<Time>["position"];
  color: string;
  shape: SeriesMarker<Time>["shape"];
  text: string;
}

interface TradingChartProps {
  candles: CandlestickData[];
  symbol: string;
}

const TradingChart = ({ candles, symbol }: TradingChartProps) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const emaSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  /** Após histórico completo (p.ex. troca de símbolo); próximas atualizações OHLC usam scroll ao tempo real. */
  const expectHistoryFitRef = useRef(true);

  const initChart = useCallback(() => {
    if (!containerRef.current) return;

    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      emaSeriesRef.current = null;
    }

    const el = containerRef.current;
    const chart = createChart(el, {
      width: el.clientWidth,
      height: el.clientHeight,
      layout: {
        background: { type: ColorType.Solid, color: "#131722" },
        textColor: "#b2b5be",
        fontFamily: "'JetBrains Mono', ui-monospace, monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "#2a2e39" },
        horzLines: { color: "#2a2e39" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#2a2e39" },
      timeScale: {
        borderColor: "#2a2e39",
        timeVisible: true,
        secondsVisible: false,
      },
      handleScale: { axisPressedMouseMove: true },
      handleScroll: { vertTouchDrag: true },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderVisible: false,
      wickUpColor: "#26a69a",
      wickDownColor: "#ef5350",
    });

    const emaSeries = chart.addSeries(LineSeries, {
      color: "#fbbf24",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: true,
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    emaSeriesRef.current = emaSeries;
  }, []);

  useEffect(() => {
    initChart();

    const handleResize = () => {
      if (chartRef.current && containerRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        });
      }
    };

    const observer = new ResizeObserver(handleResize);
    if (containerRef.current) observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
        candleSeriesRef.current = null;
        emaSeriesRef.current = null;
      }
    };
  }, [initChart]);

  useEffect(() => {
    const c = candleSeriesRef.current;
    const e = emaSeriesRef.current;
    if (!c || !e) return;

    if (candles.length === 0) {
      c.setData([]);
      e.setData([]);
      c.setMarkers([]);
      expectHistoryFitRef.current = true;
      return;
    }

    c.setData(candles);
    e.setData(computeEmaLineData(candles));
    const ts = chartRef.current?.timeScale();
    if (ts) {
      if (expectHistoryFitRef.current) {
        ts.fitContent();
        expectHistoryFitRef.current = false;
      } else {
        ts.scrollToRealTime();
      }
    }
  }, [candles]);

  useEffect(() => {
    const c = candleSeriesRef.current;
    if (c) c.setMarkers([]);
    expectHistoryFitRef.current = true;
  }, [symbol]);

  useEffect(() => {
    const c = candleSeriesRef.current;
    if (!c) return;

    let cancelled = false;

    const fetchTrades = async () => {
      try {
        const r = await fetch(`/api/trades?symbol=${encodeURIComponent(symbol)}`, {
          cache: "no-store",
        });
        if (cancelled || !r.ok) return;
        const data = (await r.json()) as TradeMarkerRow[];
        if (!Array.isArray(data) || !candleSeriesRef.current) return;
        const markers: SeriesMarker<Time>[] = data.map((m) => ({
          time: m.time,
          position: m.position,
          color: m.color,
          shape: m.shape,
          text: m.text,
        }));
        candleSeriesRef.current.setMarkers(markers);
      } catch {
        /* ignore */
      }
    };

    fetchTrades();
    const id = window.setInterval(fetchTrades, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [symbol]);

  return (
    <div className="relative overflow-hidden rounded-xl border border-border bg-[#131722] shadow-2xl shadow-black/30">
      <AILogsPanel currentSymbol={symbol} />
      <div
        ref={containerRef}
        className="h-[calc(100vh-220px)] min-h-[400px] w-full md:h-[calc(100vh-180px)]"
      />
      {candles.length === 0 && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <div className="flex flex-col items-center gap-3 text-muted-foreground">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
            <span className="font-mono text-sm">A carregar velas M5…</span>
          </div>
        </div>
      )}
    </div>
  );
};

export default TradingChart;
