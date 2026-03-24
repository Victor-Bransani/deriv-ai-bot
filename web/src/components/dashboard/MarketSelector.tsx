import { motion } from "framer-motion";

interface Market {
  value: string;
  label: string;
  description: string;
}

const markets: Market[] = [
  { value: "R_10", label: "V10", description: "Volatility 10" },
  { value: "R_25", label: "V25", description: "Volatility 25" },
  { value: "R_50", label: "V50", description: "Volatility 50" },
  { value: "R_75", label: "V75", description: "Volatility 75" },
];

interface MarketSelectorProps {
  selected: string;
  onChange: (market: string) => void;
}

const MarketSelector = ({ selected, onChange }: MarketSelectorProps) => {
  return (
    <div className="flex items-center gap-2">
      {markets.map((m) => (
        <button
          key={m.value}
          onClick={() => onChange(m.value)}
          className={`relative px-3 py-1.5 rounded-lg text-xs font-semibold font-mono transition-colors ${
            selected === m.value
              ? "text-primary-foreground"
              : "text-muted-foreground hover:text-foreground hover:bg-secondary"
          }`}
        >
          {selected === m.value && (
            <motion.div
              layoutId="market-pill"
              className="absolute inset-0 rounded-lg bg-primary glow-primary"
              transition={{ type: "spring", stiffness: 400, damping: 30 }}
            />
          )}
          <span className="relative z-10">{m.label}</span>
        </button>
      ))}
    </div>
  );
};

export default MarketSelector;
