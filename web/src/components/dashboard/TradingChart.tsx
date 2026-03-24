import { useEffect, useRef, useCallback } from "react";
import {
  createChart,
  createSeriesMarkers,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  CandlestickSeries,
  ColorType,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import { computeEma, computeMacd, computeRsi, computeSma } from "@/lib/chartIndicators";
import { apiUrl } from "@/lib/apiBase";
import { chartMainPriceFormat } from "@/lib/priceFormat";

const SMA_PERIOD = 20;
const EMA_PERIOD = 20;
const RSI_PERIOD = 14;

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

function lastOrUndefined<T>(arr: T[]): T | undefined {
  return arr.length ? arr[arr.length - 1] : undefined;
}

const TradingChart = ({ candles, symbol }: TradingChartProps) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const smaSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const emaSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const rsiSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdHistRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const macdLineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdSignalRef = useRef<ISeriesApi<"Line"> | null>(null);
  const tradeMarkersRef = useRef<ReturnType<typeof createSeriesMarkers> | null>(null);
  const expectHistoryFitRef = useRef(true);
  const prevCandlesRef = useRef<CandlestickData[]>([]);

  const initChart = useCallback(() => {
    if (!containerRef.current) return;

    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      smaSeriesRef.current = null;
      emaSeriesRef.current = null;
      rsiSeriesRef.current = null;
      macdHistRef.current = null;
      macdLineRef.current = null;
      macdSignalRef.current = null;
      tradeMarkersRef.current = null;
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
        rightOffset: 12,
        fixLeftEdge: false,
        fixRightEdge: false,
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: true,
      },
      handleScale: {
        axisPressedMouseMove: { time: true, price: true },
        mouseWheel: true,
        pinch: true,
        axisDoubleClickReset: true,
      },
      kineticScroll: {
        touch: true,
        mouse: true,
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      priceScaleId: "right",
      priceFormat: chartMainPriceFormat,
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderVisible: false,
      wickUpColor: "#26a69a",
      wickDownColor: "#ef5350",
    });

    const smaSeries = chart.addSeries(LineSeries, {
      priceScaleId: "right",
      priceFormat: chartMainPriceFormat,
      color: "#38bdf8",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: true,
    });

    const emaSeries = chart.addSeries(LineSeries, {
      priceScaleId: "right",
      priceFormat: chartMainPriceFormat,
      color: "#fbbf24",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: true,
    });

    const rsiSeries = chart.addSeries(LineSeries, {
      priceScaleId: "rsi",
      color: "#c084fc",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      priceFormat: { type: "price", precision: 1, minMove: 0.1 },
      autoscaleInfoProvider: () => ({
        priceRange: { minValue: 0, maxValue: 100 },
      }),
    });

    rsiSeries.createPriceLine({
      price: 70,
      color: "rgba(248, 113, 113, 0.45)",
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      axisLabelVisible: true,
      title: "70",
    });
    rsiSeries.createPriceLine({
      price: 30,
      color: "rgba(74, 222, 128, 0.45)",
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      axisLabelVisible: true,
      title: "30",
    });

    const macdHist = chart.addSeries(HistogramSeries, {
      priceScaleId: "macd",
      priceLineVisible: false,
      lastValueVisible: false,
    });

    const macdLine = chart.addSeries(LineSeries, {
      priceScaleId: "macd",
      color: "#3b82f6",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
    });

    const macdSignal = chart.addSeries(LineSeries, {
      priceScaleId: "macd",
      color: "#fb923c",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
    });

    // scaleMargins: top+bottom < 1. RSI: top 0,65 + bottom 0,75 > 1 na API — bottom 0,22 ~ faixa estreita ~13%.
    chart.priceScale("right").applyOptions({
      scaleMargins: { top: 0.05, bottom: 0.35 },
      borderVisible: true,
      borderColor: "#2a2e39",
    });
    chart.priceScale("rsi").applyOptions({
      scaleMargins: { top: 0.65, bottom: 0.22 },
      borderVisible: true,
      borderColor: "#2a2e39",
    });
    chart.priceScale("macd").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0.02 },
      borderVisible: true,
      borderColor: "#2a2e39",
    });

    tradeMarkersRef.current = createSeriesMarkers(candleSeries, []);

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    smaSeriesRef.current = smaSeries;
    emaSeriesRef.current = emaSeries;
    rsiSeriesRef.current = rsiSeries;
    macdHistRef.current = macdHist;
    macdLineRef.current = macdLine;
    macdSignalRef.current = macdSignal;
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
        smaSeriesRef.current = null;
        emaSeriesRef.current = null;
        rsiSeriesRef.current = null;
        macdHistRef.current = null;
        macdLineRef.current = null;
        macdSignalRef.current = null;
        tradeMarkersRef.current = null;
      }
    };
  }, [initChart]);

  useEffect(() => {
    const c = candleSeriesRef.current;
    const sma = smaSeriesRef.current;
    const ema = emaSeriesRef.current;
    const rsi = rsiSeriesRef.current;
    const mh = macdHistRef.current;
    const ml = macdLineRef.current;
    const ms = macdSignalRef.current;
    if (!c || !sma || !ema || !rsi || !mh || !ml || !ms) return;

    if (candles.length === 0) {
      c.setData([]);
      sma.setData([]);
      ema.setData([]);
      rsi.setData([]);
      mh.setData([]);
      ml.setData([]);
      ms.setData([]);
      tradeMarkersRef.current?.setMarkers([]);
      expectHistoryFitRef.current = true;
      prevCandlesRef.current = [];
      return;
    }

    const prev = prevCandlesRef.current;
    const lastBar = candles[candles.length - 1];
    const prevLast = lastOrUndefined(prev);
    const incremental =
      prev.length === candles.length &&
      prevLast !== undefined &&
      lastBar !== undefined &&
      prevLast.time === lastBar.time;

    const smaD = computeSma(candles, SMA_PERIOD);
    const emaD = computeEma(candles, EMA_PERIOD);
    const rsiD = computeRsi(candles, RSI_PERIOD);
    const macd = computeMacd(candles, 12, 26, 9);

    if (incremental) {
      c.update(lastBar);
      const ls = lastOrUndefined(smaD);
      const le = lastOrUndefined(emaD);
      const lr = lastOrUndefined(rsiD);
      const lmh = lastOrUndefined(macd.histogram);
      const lml = lastOrUndefined(macd.line);
      const lms = lastOrUndefined(macd.signal);
      if (ls) sma.update(ls);
      if (le) ema.update(le);
      if (lr) rsi.update(lr);
      if (lmh) mh.update(lmh);
      if (lml) ml.update(lml);
      if (lms) ms.update(lms);
    } else {
      c.setData(candles);
      sma.setData(smaD);
      ema.setData(emaD);
      rsi.setData(rsiD);
      mh.setData(macd.histogram);
      ml.setData(macd.line);
      ms.setData(macd.signal);
    }

    prevCandlesRef.current = candles;

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
    tradeMarkersRef.current?.setMarkers([]);
    expectHistoryFitRef.current = true;
    prevCandlesRef.current = [];
  }, [symbol]);

  useEffect(() => {
    if (!tradeMarkersRef.current) return;

    let cancelled = false;

    const fetchTrades = async () => {
      try {
        const r = await fetch(apiUrl(`/api/trades?symbol=${encodeURIComponent(symbol)}`), {
          cache: "no-store",
        });
        if (cancelled || !r.ok) return;
        const data = (await r.json()) as TradeMarkerRow[];
        if (!Array.isArray(data) || !tradeMarkersRef.current) return;
        const markers: SeriesMarker<Time>[] = data.map((m) => ({
          time: m.time,
          position: m.position,
          color: m.color,
          shape: m.shape,
          text: m.text,
        }));
        tradeMarkersRef.current.setMarkers(markers);
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
    <div className="relative flex min-h-0 min-w-0 flex-1 flex-col rounded-xl border border-border bg-[#131722] shadow-2xl shadow-black/30">
      <div
        ref={containerRef}
        className="min-h-[600px] w-full flex-1 lg:min-h-[640px]"
        style={{ height: "max(600px, 80vh)" }}
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
