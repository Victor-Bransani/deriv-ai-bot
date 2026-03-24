import { useEffect, useState } from "react";
import { History } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { HistoryRow } from "@/types/institutional";
import { apiUrl } from "@/lib/apiBase";
import { cn } from "@/lib/utils";

const POLL_MS = 15000;
const LIMIT = 40;

function fmtCell(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number" && Number.isFinite(v)) {
    return Number.isInteger(v) ? String(v) : v.toFixed(2);
  }
  return String(v);
}

function signalBadge(signal: string): string {
  const s = signal.toUpperCase();
  if (s === "MULTUP") return "bg-emerald-500/15 text-emerald-400 ring-emerald-500/25";
  if (s === "MULTDOWN") return "bg-red-500/15 text-red-400 ring-red-500/25";
  return "bg-muted text-muted-foreground ring-border";
}

const TradeHistoryPanel = () => {
  const [rows, setRows] = useState<HistoryRow[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const r = await fetch(apiUrl(`/api/history?limit=${LIMIT}`), { cache: "no-store" });
        if (cancelled) return;
        if (!r.ok) {
          setErr(`HTTP ${r.status}`);
          return;
        }
        const j = (await r.json()) as HistoryRow[];
        if (!cancelled) {
          setRows(Array.isArray(j) ? j : []);
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

  return (
    <Card className="border-border/80 bg-card/40 shadow-lg ring-1 ring-white/[0.03] backdrop-blur-md">
      <CardHeader className="flex flex-row items-center gap-3 space-y-0 pb-2 pt-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-border/60 bg-primary/10 text-primary">
          <History className="h-4 w-4" />
        </div>
        <div>
          <CardTitle className="text-base font-semibold tracking-tight">Diário de operações</CardTitle>
          <CardDescription className="text-xs">
            Sinais MULTUP / MULTDOWN · atualização automática
            {err ? <span className="ml-2 text-destructive">({err})</span> : null}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="pb-4 pt-0">
        <div className="max-h-[min(360px,45vh)] overflow-auto rounded-lg border border-border/50">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="sticky top-0 z-10 bg-card/95 text-[0.65rem] uppercase tracking-wider backdrop-blur-sm">
                  Hora (UTC)
                </TableHead>
                <TableHead className="sticky top-0 z-10 bg-card/95 text-[0.65rem] uppercase tracking-wider backdrop-blur-sm">
                  Símbolo
                </TableHead>
                <TableHead className="sticky top-0 z-10 bg-card/95 text-[0.65rem] uppercase tracking-wider backdrop-blur-sm">
                  Sinal
                </TableHead>
                <TableHead className="sticky top-0 z-10 bg-card/95 text-[0.65rem] uppercase tracking-wider backdrop-blur-sm">
                  Conf.
                </TableHead>
                <TableHead className="sticky top-0 z-10 bg-card/95 text-[0.65rem] uppercase tracking-wider backdrop-blur-sm">
                  RSI
                </TableHead>
                <TableHead className="sticky top-0 z-10 hidden bg-card/95 text-[0.65rem] uppercase tracking-wider backdrop-blur-sm md:table-cell">
                  Motivo
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="py-10 text-center text-sm text-muted-foreground">
                    Sem entradas no CSV ou gestor sem dados partilhados.
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((row, i) => (
                  <TableRow key={`${row.ts_utc_iso}-${row.symbol_deriv}-${i}`} className="group">
                    <TableCell className="whitespace-nowrap font-mono text-xs text-muted-foreground">
                      {fmtCell(row.ts_utc_iso)}
                    </TableCell>
                    <TableCell className="font-mono text-xs font-medium">{fmtCell(row.symbol_deriv)}</TableCell>
                    <TableCell>
                      <span
                        className={cn(
                          "inline-flex rounded-md px-2 py-0.5 text-[0.7rem] font-semibold uppercase ring-1 ring-inset",
                          signalBadge(String(row.signal ?? "")),
                        )}
                      >
                        {fmtCell(row.signal)}
                      </span>
                    </TableCell>
                    <TableCell className="font-mono text-xs">{fmtCell(row.confidence)}</TableCell>
                    <TableCell className="font-mono text-xs">{fmtCell(row.rsi_m5)}</TableCell>
                    <TableCell className="hidden max-w-[220px] truncate text-xs text-muted-foreground md:table-cell md:max-w-[320px]">
                      <span title={String(row.reason ?? "")}>{fmtCell(row.reason)}</span>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
};

export default TradeHistoryPanel;
