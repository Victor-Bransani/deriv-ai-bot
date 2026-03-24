import { useEffect, useState } from "react";
import type { LucideIcon } from "lucide-react";
import { Activity, Landmark, Radio, TrendingDown, TrendingUp, Wallet } from "lucide-react";
import type { StatsPayload } from "@/types/institutional";
import { apiUrl } from "@/lib/apiBase";
import { cn } from "@/lib/utils";

const POLL_MS = 8000;

function fmtMoney(n: number): string {
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n);
}

function KpiTile({
  label,
  value,
  sub,
  icon: Icon,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  icon: LucideIcon;
  accent: "slate" | "emerald" | "amber" | "violet" | "sky";
}) {
  const iconTint =
    accent === "emerald"
      ? "text-emerald-400/90"
      : accent === "amber"
        ? "text-amber-400/90"
        : accent === "violet"
          ? "text-violet-400/90"
          : accent === "sky"
            ? "text-sky-400/90"
            : "text-slate-400";
  return (
    <div className="relative rounded-xl border border-border/80 bg-card/75 p-4 shadow-sm ring-1 ring-white/[0.04] backdrop-blur-md">
      <div className="relative flex items-start justify-between gap-2">
        <div>
          <p className="text-[0.65rem] font-semibold uppercase tracking-wider text-muted-foreground">{label}</p>
          <p className="mt-1 font-mono text-xl font-bold tabular-nums tracking-tight text-foreground md:text-2xl">
            {value}
          </p>
          {sub ? <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p> : null}
        </div>
        <div className={cn("rounded-lg border border-border/60 bg-background/50 p-2", iconTint)}>
          <Icon className="h-4 w-4" />
        </div>
      </div>
    </div>
  );
}

const InstitutionalKpiBar = () => {
  const [stats, setStats] = useState<StatsPayload | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const r = await fetch(apiUrl("/api/stats"), { cache: "no-store" });
        if (cancelled) return;
        if (!r.ok) {
          setErr(`HTTP ${r.status}`);
          return;
        }
        const j = (await r.json()) as StatsPayload;
        if (!cancelled) {
          setStats(j);
          setErr(null);
        }
      } catch {
        if (!cancelled) setErr("Rede");
      }
    };

    load();
    const id = window.setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const pnl = stats?.global_daily_pnl ?? 0;
  const pnlUp = pnl >= 0;

  return (
    <section className="mb-4 space-y-3" aria-label="KPIs institucionais">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiTile
          label="Banca (conta)"
          value={stats != null ? `${fmtMoney(stats.global_balance)} USD` : "—"}
          sub={err ? `Gestor: ${err}` : "Mesma conta · saldo real (1×)"}
          icon={Wallet}
          accent="sky"
        />
        <KpiTile
          label="PnL dia (Σ)"
          value={stats != null ? `${pnlUp ? "+" : ""}${fmtMoney(pnl)} USD` : "—"}
          sub={stats != null ? (pnlUp ? "Acima da água" : "Pressão no dia") : undefined}
          icon={pnlUp ? TrendingUp : TrendingDown}
          accent={pnlUp ? "emerald" : "amber"}
        />
        <KpiTile
          label="Trades hoje"
          value={stats != null ? String(stats.total_daily_trades) : "—"}
          sub="MULTUP/MULTDOWN (UTC)"
          icon={Activity}
          accent="violet"
        />
        <KpiTile
          label="Operários online"
          value={stats != null ? `${stats.online_workers} / 4` : "—"}
          sub="Workers HTTP /status"
          icon={Radio}
          accent="slate"
        />
      </div>

      {stats?.workers_detail ? (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border/70 bg-muted/20 px-3 py-2.5">
          <Landmark className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <span className="text-[0.65rem] font-semibold uppercase tracking-wider text-muted-foreground">Workers</span>
          <div className="flex flex-wrap gap-2">
            {Object.entries(stats.workers_detail).map(([sym, w]) => {
              const on = w.status === "online";
              return (
                <div
                  key={sym}
                  className={cn(
                    "flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-mono",
                    on
                      ? "border-emerald-500/30 bg-emerald-500/5 text-foreground"
                      : "border-border bg-background/40 text-muted-foreground",
                  )}
                >
                  <span
                    className={cn("h-1.5 w-1.5 rounded-full", on ? "bg-emerald-400 shadow-[0_0_6px_#4ade80]" : "bg-muted-foreground/50")}
                  />
                  <span className="font-semibold">{sym}</span>
                  {on && w.balance != null ? (
                    <span className="text-muted-foreground">{fmtMoney(w.balance)}</span>
                  ) : (
                    <span className="max-w-[120px] truncate text-[0.7rem] normal-case text-rose-400/90">{w.error}</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
    </section>
  );
};

export default InstitutionalKpiBar;
