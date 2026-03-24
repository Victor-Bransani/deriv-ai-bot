import { useEffect, useState } from "react";
import { apiUrl } from "@/lib/apiBase";

export interface CyclePayload {
  phase?: string | number | boolean;
  signal?: string | number | boolean;
  rsi_m5?: string | number | boolean;
  m15_tide?: string | number | boolean;
  obi?: string | number | boolean;
  reason?: string | number | boolean;
}

function fmtCell(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "sim" : "não";
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  return String(v);
}

function parseRsi(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = typeof v === "number" ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n : null;
}

function fmtRsi(v: unknown): string {
  const n = parseRsi(v);
  return n === null ? "—" : n.toFixed(2);
}

function rsiTone(v: unknown): string {
  const n = parseRsi(v);
  if (n === null) return "font-mono text-slate-500";
  if (n >= 70) return "font-mono font-semibold text-red-400 tabular-nums";
  if (n <= 30) return "font-mono font-semibold text-emerald-400 tabular-nums";
  return "font-mono text-slate-200 tabular-nums";
}

function signalTone(signal: string): string {
  const s = signal.toUpperCase();
  if (s === "WAIT" || s === "" || s === "—") return "text-amber-400 font-semibold";
  if (s.includes("UP")) return "text-emerald-400 font-semibold";
  if (s.includes("DOWN")) return "text-red-400 font-semibold";
  return "text-slate-100 font-semibold";
}

interface AILogsPanelProps {
  currentSymbol: string;
}

const AILogsPanel = ({ currentSymbol }: AILogsPanelProps) => {
  const [data, setData] = useState<CyclePayload | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const r = await fetch(apiUrl(`/api/cycle?symbol=${encodeURIComponent(currentSymbol)}`), {
          cache: "no-store",
        });
        if (cancelled) return;
        if (r.status === 404) {
          setData(null);
          return;
        }
        if (!r.ok) return;
        const json = (await r.json()) as CyclePayload;
        if (!cancelled) setData(json);
      } catch {
        if (!cancelled) setData(null);
      }
    };

    load();
    const id = window.setInterval(load, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [currentSymbol]);

  const signalStr = data?.signal != null ? fmtCell(data.signal) : "—";
  const phaseStr = data?.phase != null ? fmtCell(data.phase) : "—";

  return (
    <aside
      className="flex h-full min-h-0 min-w-0 flex-col rounded-xl border border-slate-600/70 bg-slate-900/50 p-4 text-white shadow-xl backdrop-blur-sm lg:max-w-none"
      aria-label="Estado da IA"
    >
      <h2 className="mb-3 shrink-0 border-b border-slate-600/50 pb-2 text-[0.65rem] font-bold uppercase tracking-[0.18em] text-slate-400">
        Terminal IA
      </h2>
      <dl className="grid shrink-0 grid-cols-[minmax(0,7rem)_1fr] gap-x-3 gap-y-2.5 text-sm leading-tight">
        <dt className="text-slate-500">Fase</dt>
        <dd className="font-mono text-slate-100">{phaseStr}</dd>
        <dt className="text-slate-500">Sinal</dt>
        <dd className={`font-mono ${signalTone(signalStr)}`}>{signalStr}</dd>
        <dt className="text-slate-500">RSI (M5)</dt>
        <dd className={rsiTone(data?.rsi_m5)}>{fmtRsi(data?.rsi_m5)}</dd>
        <dt className="text-slate-500">Maré (M15)</dt>
        <dd className="font-mono text-slate-200">{data ? fmtCell(data.m15_tide) : "—"}</dd>
        <dt className="text-slate-500">OBI</dt>
        <dd className="font-mono text-slate-200">{data ? fmtCell(data.obi) : "—"}</dd>
      </dl>
      <p className="mt-3 min-h-0 flex-1 overflow-y-auto border-t border-slate-600/50 pt-2 text-xs leading-relaxed text-slate-400">
        {data?.reason != null && String(data.reason).trim() !== ""
          ? String(data.reason)
          : "Sem dados de ciclo para este símbolo (operário + CSV ativos)."}
      </p>
    </aside>
  );
};

export default AILogsPanel;
