import { Wifi, WifiOff, Loader2 } from "lucide-react";

export type ConnectionStatus = "connecting" | "connected" | "error" | "idle";

interface StatusIndicatorProps {
  status: ConnectionStatus;
  message?: string;
}

const statusConfig = {
  connecting: {
    icon: Loader2,
    color: "text-warning",
    bg: "bg-warning/10",
    border: "border-warning/20",
    label: "A ligar…",
    animate: true,
  },
  connected: {
    icon: Wifi,
    color: "text-success",
    bg: "bg-success/10",
    border: "border-success/20",
    label: "Ligado",
    animate: false,
  },
  error: {
    icon: WifiOff,
    color: "text-danger",
    bg: "bg-danger/10",
    border: "border-danger/20",
    label: "Erro",
    animate: false,
  },
  idle: {
    icon: Wifi,
    color: "text-muted-foreground",
    bg: "bg-muted/50",
    border: "border-border",
    label: "Desligado",
    animate: false,
  },
};

const StatusIndicator = ({ status, message }: StatusIndicatorProps) => {
  const cfg = statusConfig[status];
  const Icon = cfg.icon;

  return (
    <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border ${cfg.bg} ${cfg.border}`}>
      <Icon className={`w-3.5 h-3.5 ${cfg.color} ${cfg.animate ? "animate-spin" : ""}`} />
      <span className={`text-xs font-mono ${cfg.color}`}>
        {message || cfg.label}
      </span>
    </div>
  );
};

export default StatusIndicator;
