import { useEffect, useState } from "react";

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

function fmtRsi(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "number" ? v : parseFloat(String(v));
  if (!Number.isFinite(n)) return "—";
  return n.toFixed(2);
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
        const r = await fetch(`/api/cycle?symbol=${encodeURIComponent(currentSymbol)}`, {
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
      className="pointer-events-none absolute top-4 right-4 z-50 min-w-[300px] max-w-[min(100%-2rem,380px)] rounded-xl border border-slate-700/50 bg-slate-900/60 p-4 text-white shadow-2xl backdrop-blur-md"
      aria-label="Estado da IA"
    >
      <h2 className="mb-3 border-b border-slate-700/40 pb-2 text-[0.65rem] font-bold uppercase tracking-[0.2em] text-slate-400">
        Estado da IA
      </h2>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
        <dt className="text-slate-500">Fase</dt>
        <dd className="font-mono text-slate-100">{phaseStr}</dd>
        <dt className="text-slate-500">Sinal</dt>
        <dd className={`font-mono ${signalTone(signalStr)}`}>{signalStr}</dd>
        <dt className="text-slate-500">RSI (M5)</dt>
        <dd className="font-mono text-cyan-300/90">{fmtRsi(data?.rsi_m5)}</dd>
        <dt className="text-slate-500">Maré (M15)</dt>
        <dd className="font-mono text-slate-200">{data ? fmtCell(data.m15_tide) : "—"}</dd>
        <dt className="text-slate-500">OBI</dt>
        <dd className="font-mono text-slate-200">{data ? fmtCell(data.obi) : "—"}</dd>
      </dl>
      <p className="mt-3 border-t border-slate-700/40 pt-2 text-xs leading-relaxed text-slate-400">
        {data?.reason != null && String(data.reason).trim() !== ""
          ? String(data.reason)
          : "Sem dados de ciclo para este símbolo (operário + CSV ativos)."}
      </p>
    </aside>
  );
};

export default AILogsPanel;
