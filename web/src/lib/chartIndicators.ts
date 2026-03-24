import type { CandlestickData, HistogramData, LineData, Time } from "lightweight-charts";

function closesAndTimes(bars: CandlestickData[]): { closes: number[]; times: Time[] } {
  const closes = bars.map((b) => b.close);
  const times = bars.map((b) => b.time);
  return { closes, times };
}

/** SMA: primeiro ponto no índice period - 1. */
export function computeSma(bars: CandlestickData[], period: number): LineData[] {
  if (bars.length < period) return [];
  const { closes, times } = closesAndTimes(bars);
  const out: LineData[] = [];
  for (let i = period - 1; i < closes.length; i++) {
    let s = 0;
    for (let j = 0; j < period; j++) s += closes[i - j];
    out.push({ time: times[i], value: s / period });
  }
  return out;
}

/** EMA clássica: primeiro valor = SMA(period), depois multiplicador k = 2/(period+1). */
export function computeEma(bars: CandlestickData[], period: number): LineData[] {
  if (bars.length < period) return [];
  const { closes, times } = closesAndTimes(bars);
  const k = 2 / (period + 1);
  let ema = 0;
  for (let i = 0; i < period; i++) ema += closes[i];
  ema /= period;
  const out: LineData[] = [{ time: times[period - 1], value: ema }];
  for (let i = period; i < closes.length; i++) {
    ema = closes[i] * k + ema * (1 - k);
    out.push({ time: times[i], value: ema });
  }
  return out;
}

/** RSI Wilder (14). Primeiro RSI no índice `period` (precisa de period fechos de variação). */
export function computeRsi(bars: CandlestickData[], period: number): LineData[] {
  if (bars.length < period + 1) return [];
  const { closes, times } = closesAndTimes(bars);
  const out: LineData[] = [];

  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const ch = closes[i] - closes[i - 1];
    avgGain += ch > 0 ? ch : 0;
    avgLoss += ch < 0 ? -ch : 0;
  }
  avgGain /= period;
  avgLoss /= period;

  const pushRsi = (idx: number) => {
    if (avgLoss === 0) out.push({ time: times[idx], value: 100 });
    else if (avgGain === 0) out.push({ time: times[idx], value: 0 });
    else {
      const rs = avgGain / avgLoss;
      out.push({ time: times[idx], value: 100 - 100 / (1 + rs) });
    }
  };

  pushRsi(period);

  for (let i = period + 1; i < closes.length; i++) {
    const ch = closes[i] - closes[i - 1];
    const g = ch > 0 ? ch : 0;
    const l = ch < 0 ? -ch : 0;
    avgGain = (avgGain * (period - 1) + g) / period;
    avgLoss = (avgLoss * (period - 1) + l) / period;
    pushRsi(i);
  }
  return out;
}

export interface MacdComputed {
  line: LineData[];
  signal: LineData[];
  histogram: HistogramData[];
}

/**
 * MACD(12,26,9): linha = EMA12 − EMA26; signal = EMA9 da linha MACD; histograma = linha − signal.
 */
export function computeMacd(
  bars: CandlestickData[],
  fast = 12,
  slow = 26,
  signalPeriod = 9,
): MacdComputed {
  const line: LineData[] = [];
  const signal: LineData[] = [];
  const histogram: HistogramData[] = [];

  if (bars.length < slow) return { line, signal, histogram };

  const { closes, times } = closesAndTimes(bars);
  const emaFast = emaValues(closes, fast);
  const emaSlow = emaValues(closes, slow);

  for (let i = slow - 1; i < closes.length; i++) {
    const f = emaFast[i];
    const s = emaSlow[i];
    if (f === undefined || s === undefined) continue;
    line.push({ time: times[i], value: f - s });
  }

  if (line.length < signalPeriod) return { line, signal, histogram };

  const macdVals = line.map((p) => p.value);
  const kSig = 2 / (signalPeriod + 1);
  let sigEma = 0;
  for (let i = 0; i < signalPeriod; i++) sigEma += macdVals[i];
  sigEma /= signalPeriod;

  const firstSigIdx = signalPeriod - 1;
  signal.push({ time: line[firstSigIdx].time, value: sigEma });
  let h = macdVals[firstSigIdx] - sigEma;
  histogram.push({
    time: line[firstSigIdx].time,
    value: h,
    color: h >= 0 ? "#26a69a" : "#ef5350",
  });

  for (let i = signalPeriod; i < macdVals.length; i++) {
    const m = macdVals[i];
    sigEma = m * kSig + sigEma * (1 - kSig);
    const t = line[i].time;
    signal.push({ time: t, value: sigEma });
    h = m - sigEma;
    histogram.push({
      time: t,
      value: h,
      color: h >= 0 ? "#26a69a" : "#ef5350",
    });
  }

  return { line, signal, histogram };
}

function emaValues(closes: number[], period: number): (number | undefined)[] {
  const out: (number | undefined)[] = Array(closes.length).fill(undefined);
  if (closes.length < period) return out;
  const k = 2 / (period + 1);
  let ema = 0;
  for (let i = 0; i < period; i++) ema += closes[i];
  ema /= period;
  out[period - 1] = ema;
  for (let i = period; i < closes.length; i++) {
    ema = closes[i] * k + ema * (1 - k);
    out[i] = ema;
  }
  return out;
}
