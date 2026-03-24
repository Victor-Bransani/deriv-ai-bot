import { motion, AnimatePresence } from "framer-motion";
import { TrendingUp, TrendingDown } from "lucide-react";
import { formatPrice } from "@/lib/priceFormat";

interface PriceDisplayProps {
  price: number | null;
  previousPrice: number | null;
}

const PriceDisplay = ({ price, previousPrice }: PriceDisplayProps) => {
  if (price === null) return null;

  const direction = previousPrice !== null
    ? price > previousPrice ? "up" : price < previousPrice ? "down" : "neutral"
    : "neutral";

  const colorClass = direction === "up" ? "text-success" : direction === "down" ? "text-danger" : "text-foreground";

  return (
    <div className="flex items-center gap-3">
      <AnimatePresence mode="popLayout">
        <motion.span
          key={price}
          initial={{ y: direction === "up" ? 8 : -8, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: direction === "up" ? -8 : 8, opacity: 0 }}
          transition={{ duration: 0.2 }}
          className={`text-2xl md:text-3xl font-bold font-mono tabular-nums ${colorClass}`}
        >
          {formatPrice(price)}
        </motion.span>
      </AnimatePresence>
      {direction !== "neutral" && (
        <motion.div
          initial={{ scale: 0 }}
          animate={{ scale: 1 }}
          className={`p-1 rounded-md ${direction === "up" ? "bg-success/10" : "bg-danger/10"}`}
        >
          {direction === "up" ? (
            <TrendingUp className="w-4 h-4 text-success" />
          ) : (
            <TrendingDown className="w-4 h-4 text-danger" />
          )}
        </motion.div>
      )}
    </div>
  );
};

export default PriceDisplay;
