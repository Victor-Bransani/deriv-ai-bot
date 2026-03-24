import { useState } from "react";
import { motion } from "framer-motion";
import { Activity, BarChart3 } from "lucide-react";
import MarketSelector from "@/components/dashboard/MarketSelector";
import StatusIndicator from "@/components/dashboard/StatusIndicator";
import PriceDisplay from "@/components/dashboard/PriceDisplay";
import AILogsPanel from "@/components/dashboard/AILogsPanel";
import InstitutionalKpiBar from "@/components/dashboard/InstitutionalKpiBar";
import TradeHistoryPanel from "@/components/dashboard/TradeHistoryPanel";
import TradingChart from "@/components/dashboard/TradingChart";
import { useDeriv } from "@/hooks/useDeriv";

const Index = () => {
  const [market, setMarket] = useState("R_75");
  const { status, statusMessage, candles, currentPrice, previousPrice } = useDeriv(market);

  const marketLabels: Record<string, string> = {
    R_10: "Volatility 10",
    R_25: "Volatility 25",
    R_50: "Volatility 50",
    R_75: "Volatility 75",
  };

  return (
    <div className="min-h-screen bg-gradient-radial">
      {/* Header */}
      <header className="glass border-b border-border sticky top-0 z-50">
        <div className="container flex flex-col md:flex-row items-start md:items-center justify-between gap-4 py-3">
          {/* Logo & Title */}
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-primary/10 border border-primary/20">
              <BarChart3 className="w-5 h-5 text-primary" />
            </div>
            <div>
              <h1 className="text-base font-bold tracking-tight flex items-center gap-2">
                Real-Time M5
                <span className="w-2 h-2 rounded-full bg-success animate-pulse-dot shadow-[0_0_8px_hsl(var(--success))]" />
              </h1>
              <p className="text-xs text-muted-foreground">{marketLabels[market]}</p>
            </div>
          </div>

          {/* Controls */}
          <div className="flex flex-wrap items-center gap-3">
            <MarketSelector selected={market} onChange={setMarket} />
            <div className="w-px h-6 bg-border hidden md:block" />
            <StatusIndicator status={status} message={statusMessage} />
          </div>
        </div>
      </header>

      {/* Main */}
      <main className="container py-4">
        <InstitutionalKpiBar />

        {/* Price Bar */}
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 mb-4"
        >
          <PriceDisplay price={currentPrice} previousPrice={previousPrice} />
          <div className="flex items-center gap-2 text-xs text-muted-foreground font-mono">
            <Activity className="w-3.5 h-3.5" />
            <span>{candles.length} velas</span>
            <span className="text-border">·</span>
            <span>M5</span>
          </div>
        </motion.div>

        {/* Terminal: gráfico + painel lateral (sem sobreposição) */}
        <motion.div
          initial={{ opacity: 0, scale: 0.98 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.1, duration: 0.4 }}
          className="flex min-h-0 flex-col gap-4 lg:grid lg:grid-cols-12 lg:items-stretch lg:gap-4 lg:min-h-[min(82vh,calc(100vh-160px))]"
        >
          <div className="flex min-h-0 flex-col lg:col-span-9">
            <TradingChart candles={candles} symbol={market} />
          </div>
          <div className="min-h-[280px] shrink-0 lg:col-span-3 lg:min-h-[min(82vh,calc(100vh-160px))]">
            <AILogsPanel currentSymbol={market} />
          </div>
        </motion.div>

        <div className="mt-6">
          <TradeHistoryPanel />
        </div>
      </main>

      {/* Footer */}
      <footer className="container py-3">
        <p className="text-xs text-muted-foreground font-mono text-center">
          Lightweight Charts · M5 · /api/stats · /api/history · /api/trades · /api/cycle
        </p>
      </footer>
    </div>
  );
};

export default Index;
