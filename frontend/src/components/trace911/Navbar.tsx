import { useEffect, useState } from "react";
import { Radio, RefreshCw } from "lucide-react";
import ThemeToggle from "./ThemeToggle";
import { audioBus } from "./audioBus";

export default function Navbar() {
  const [time, setTime] = useState(() => new Date().toLocaleTimeString("en-GB", { hour12: false }));
  const [resetting, setResetting] = useState(false);

  useEffect(() => {
    const id = setInterval(() => {
      setTime(new Date().toLocaleTimeString("en-GB", { hour12: false }));
    }, 1000);
    return () => clearInterval(id);
  }, []);

  const handleReset = async () => {
    if (resetting) return;
    setResetting(true);
    audioBus.emitDemo("reset");
    try {
      await fetch("http://localhost:5000/reset", { method: "POST" });
    } catch (e) {
      console.error("Failed to reset", e);
    } finally {
      setTimeout(() => setResetting(false), 500);
    }
  };

  return (
    <header className="h-14 w-full bg-card border-b border-border flex items-center px-5 transition-colors">
      <div className="flex items-center gap-2 flex-1">
        <Radio className="w-5 h-5 text-[hsl(var(--signal-red))]" />
        <span className="font-bold text-base tracking-tight">Trace911</span>
      </div>
      <div className="hidden sm:block flex-1 text-center">
        <span className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
          Live Dispatch Monitor
        </span>
      </div>
      <div className="flex items-center gap-4 flex-1 justify-end">
        <ThemeToggle />
        <button
          type="button"
          onClick={handleReset}
          disabled={resetting}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold text-white hover:opacity-90 transition-opacity disabled:opacity-60"
          style={{ backgroundColor: "#6c757d" }}
        >
          <RefreshCw className={`w-3.5 h-3.5 ${resetting ? "animate-spin" : ""}`} />
        </button>
        <div className="flex items-center gap-2">
          <span className="live-dot" />
          <span className="text-xs font-semibold text-[hsl(var(--signal-red))]">LIVE</span>
        </div>
        <span className="font-mono text-sm tabular-nums text-foreground/80">{time}</span>
      </div>
    </header>
  );
}
