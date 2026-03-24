export interface WorkerDetail {
  balance: number | null;
  daily_pnl: number | null;
  status: "online" | "offline" | string;
  running: boolean;
  last_signal?: string;
  error?: string;
}

export interface StatsPayload {
  global_balance: number;
  global_daily_pnl: number;
  total_daily_trades: number;
  online_workers: number;
  workers_detail: Record<string, WorkerDetail>;
}

export interface HistoryRow {
  ts_utc_iso?: string;
  symbol_deriv?: string;
  signal?: string;
  reason?: string;
  rsi_m5?: number | string;
  m15_tide?: number | string;
  obi?: number | string;
  confidence?: number | string;
}
