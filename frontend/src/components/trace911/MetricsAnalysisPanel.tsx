import { useEffect, useRef, useState } from "react";
import { audioBus } from "./audioBus";

const METRICS_URL = "http://localhost:5000/metrics";
const ANALYSIS_URL = "http://localhost:5000/analysis";

type Metrics = { wer_with: number; wer_without: number; gain: number };
type Urgency = "unknown" | "low" | "medium" | "high" | "critical";
type KeyInfo = {
  immediate_danger?: boolean;
  address?: string | null;
};
type Analysis = {
  urgency: Urgency;
  sentiment: number;          // -1..1
  emergency_type: string;     // Fire | Medical | Assault | Unknown
  immediate_danger: boolean;
  location: string | null;
  summary: string;
  action: string;
  key_info?: KeyInfo;
};

const DEFAULT_METRICS: Metrics = { wer_with: 3.1, wer_without: 34.2, gain: 91 };
const DEFAULT_ANALYSIS: Analysis = {
  urgency: "unknown",
  sentiment: 0.0,
  emergency_type: "Unknown",
  immediate_danger: false,
  location: null,
  summary: "No active call. System ready.",
  action: "Awaiting call data.",
};

const URGENCY_MAP: Record<Urgency, { label: string; bg: string; fg: string; pulse?: boolean }> = {
  unknown:  { label: "STANDBY",  bg: "hsl(var(--muted))", fg: "hsl(var(--muted-foreground))" },
  low:      { label: "LOW",      bg: "hsl(var(--muted))", fg: "hsl(var(--muted-foreground))" },
  medium:   { label: "MEDIUM",   bg: "#f4a261", fg: "#1a1a2e" },
  high:     { label: "HIGH",     bg: "#e76f51", fg: "#ffffff" },
  critical: { label: "CRITICAL", bg: "#e63946", fg: "#ffffff", pulse: true },
};

function MetricCard({ value, color, label, sub }: { value: string; color: string; label: string; sub: string }) {
  return (
    <div className="flex-1 rounded-lg border border-border p-4 bg-card flex flex-col gap-1 transition-colors">
      <div className="text-2xl font-bold tabular-nums" style={{ color }}>{value}</div>
      <div className="text-xs font-medium">{label}</div>
      <div className="text-[11px] text-muted-foreground">{sub}</div>
    </div>
  );
}

export default function MetricsAnalysisPanel() {
  const [metrics, setMetrics] = useState<Metrics>(DEFAULT_METRICS);
  const [analysis, setAnalysis] = useState<Analysis>(DEFAULT_ANALYSIS);
  const [dispatched, setDispatched] = useState(false);
  const [autoDispatched, setAutoDispatched] = useState(false);
  const [dispatchAddress, setDispatchAddress] = useState<string>("location being confirmed");
  const [metricsRevealed, setMetricsRevealed] = useState(false);
  const [polling, setPolling] = useState(true);
  const analysisRef = useRef<Analysis>(DEFAULT_ANALYSIS);
  const dispatchedRef = useRef(false);

  const handleSendHelp = (auto = false) => {
    setDispatched((prev) => {
      if (prev) return prev;
      setAutoDispatched(auto);
      setDispatchAddress((prevAddr) => {
        const a = analysisRef.current;
        return a?.location ?? a?.key_info?.address ?? "location being confirmed";
      });
      if (auto) {
        try {
          const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
          const o = ctx.createOscillator();
          const g = ctx.createGain();
          o.connect(g); g.connect(ctx.destination);
          o.type = "sine"; o.frequency.value = 880;
          g.gain.setValueAtTime(0.0001, ctx.currentTime);
          g.gain.exponentialRampToValueAtTime(0.15, ctx.currentTime + 0.02);
          g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.35);
          o.start();
          o.stop(ctx.currentTime + 0.4);
        } catch { /* ignore */ }
      }
      return true;
    });
  };

  useEffect(() => {
    const unsub = audioBus.subscribeDemo((event) => {
      if (event === "started") {
        setDispatched(false);
        setAutoDispatched(false);
        dispatchedRef.current = false;
        setPolling(true);
      } else if (event === "reset") {
        setDispatched(false);
        setAutoDispatched(false);
        dispatchedRef.current = false;
        setAnalysis(DEFAULT_ANALYSIS);
        analysisRef.current = DEFAULT_ANALYSIS;
        setMetricsRevealed(false);
        setDispatchAddress("location being confirmed");
        setPolling(false);
      }
    });
    return () => { unsub(); };
  }, []);

  useEffect(() => {
    analysisRef.current = analysis;
  }, [analysis]);

  useEffect(() => {
    dispatchedRef.current = dispatched;
  }, [dispatched]);

  useEffect(() => {
    fetch(METRICS_URL)
      .then((r) => {
        if (!r.ok) throw new Error("bad status");
        return r.json();
      })
      .then((d) => {
        if (!d) return;
        setMetrics({
          wer_with: Number(d.wer_with ?? d.with ?? DEFAULT_METRICS.wer_with),
          wer_without: Number(d.wer_without ?? d.without ?? DEFAULT_METRICS.wer_without),
          gain: Number(d.gain ?? d.accuracy_gain ?? DEFAULT_METRICS.gain),
        });
      })
  }, []);

  useEffect(() => {
    const fetchAnalysis = async () => {
      try {
        const r = await fetch(ANALYSIS_URL);
        if (!r.ok) throw new Error("bad status");
        const d = await r.json();
        const urgency = (d.urgency ?? "unknown") as Urgency;
        const rawAction = d.dispatcher_action ?? d.action ?? d.recommended_action ?? "";
        const trimmedAction = typeof rawAction === "string" ? rawAction.trim() : "";
        const knownUrgency = urgency !== "unknown";
        const action = trimmedAction
          ? trimmedAction
          : knownUrgency
            ? "Monitor situation and await further information"
            : DEFAULT_ANALYSIS.action;
        const key_info: KeyInfo = {
          immediate_danger: Boolean(d.key_info?.immediate_danger ?? d.immediate_danger),
          address: d.key_info?.address ?? d.location ?? null,
        };
        const next: Analysis = {
          urgency,
          sentiment: Number(d.sentiment ?? 0),
          emergency_type: d.emergency_type ?? d.type ?? "Unknown",
          immediate_danger: Boolean(d.immediate_danger ?? key_info.immediate_danger),
          location: d.location ?? key_info.address ?? null,
          summary: d.summary ?? DEFAULT_ANALYSIS.summary,
          action,
          key_info,
        };
        setAnalysis(next);
        analysisRef.current = next;

        const shouldAutoDispatch =
          (next.urgency === "critical" || next.urgency === "high") &&
          next.key_info?.immediate_danger === true &&
          next.key_info?.address != null &&
          !dispatchedRef.current;
        if (shouldAutoDispatch) {
          handleSendHelp(true);
        }
      } catch { /* ignore */ }
    };
    if (!polling) return;
    fetchAnalysis();
    const id = setInterval(fetchAnalysis, 5000);
    return () => clearInterval(id);
  }, [polling]);

  const urgencyStyle = URGENCY_MAP[analysis.urgency] ?? URGENCY_MAP.unknown;
  const sentimentPct = Math.max(0, Math.min(100, ((analysis.sentiment + 1) / 2) * 100));

  return (
    <section className="panel p-5 flex flex-col gap-5 min-h-0 overflow-y-auto">
      {/* Metrics */}
      <div>
        <h2 className="text-sm font-semibold mb-3">Audio Intelligence Metrics</h2>
        {!metricsRevealed ? (
          <button
            type="button"
            onClick={() => setMetricsRevealed(true)}
            className="w-full rounded-md border border-dashed border-border py-3 text-sm font-medium text-muted-foreground hover:bg-muted/40 transition-colors"
          >
            Reveal Audio Intelligence Metrics
          </button>
        ) : (
          <div className="flex flex-col gap-2 animate-fade-in">
            <div className="flex flex-col sm:flex-row gap-3">
              <MetricCard value={`${metrics.wer_with}%`} color="#2a9d8f" label="With ai-coustics" sub="Word Error Rate" />
              <MetricCard value={`${metrics.wer_without}%`} color="#e63946" label="Without ai-coustics" sub="Word Error Rate" />
              <MetricCard value={`${metrics.gain}%`} color="#1d3557" label="Accuracy Gain" sub="Powered by ai-coustics" />
            </div>
            <button
              type="button"
              onClick={() => setMetricsRevealed(false)}
              className="self-end text-xs text-muted-foreground hover:text-foreground underline underline-offset-2"
            >
              Hide
            </button>
          </div>
        )}
      </div>

      <div className="h-px bg-border" />

      {/* AI Analysis */}
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">AI Analysis</h2>
          <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Gemini</span>
        </div>

        {/* Dispatch success banner */}
        {dispatched && (
          <div className="flex flex-col gap-1">
            <div
              className="w-full rounded-md py-2.5 px-3 text-center text-sm font-bold tracking-wide"
              style={{ backgroundColor: "#2a9d8f", color: "#ffffff" }}
            >
              {autoDispatched
                ? `AI AUTO-DISPATCHED — Units en route to ${dispatchAddress}`
                : `RESPONSE DISPATCHED — Units en route to ${dispatchAddress}`}
            </div>
            {autoDispatched && (
              <div className="text-[11px] text-center italic text-muted-foreground">
                Automatically dispatched by Trace911 AI
              </div>
            )}
          </div>
        )}
        {/* Urgency */}
        <div
          className={`w-full rounded-full py-3 text-center text-base font-bold tracking-wider transition-colors ${urgencyStyle.pulse ? "critical-pulse" : ""}`}
          style={{ backgroundColor: urgencyStyle.bg, color: urgencyStyle.fg }}
        >
          {urgencyStyle.label}
        </div>

        {/* Sentiment */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xs font-medium">Caller Sentiment</span>
            <span className="text-xs font-mono tabular-nums text-muted-foreground">
              {analysis.sentiment.toFixed(1)}
            </span>
          </div>
          <div className="relative h-2.5 rounded-full overflow-hidden" style={{ background: "linear-gradient(to right, #e63946, #f4a261, #2a9d8f)" }}>
            <div
              className="absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-white border-2 border-foreground transition-[left] duration-500"
              style={{ left: `calc(${sentimentPct}% - 6px)` }}
            />
          </div>
          <div className="flex justify-between text-[10px] text-muted-foreground mt-1">
            <span>Panic</span><span>Calm</span>
          </div>
        </div>

        {/* Emergency type */}
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium">Emergency Type</span>
          <span className="px-3 py-1 rounded-full bg-muted text-foreground text-xs font-medium capitalize">
            {(analysis.emergency_type || "Unknown").toLowerCase()}
          </span>
        </div>

        {/* Immediate danger — high/critical urgency always shows danger */}
        {(() => {
          const isDanger =
            analysis.urgency === "high" ||
            analysis.urgency === "critical" ||
            analysis.immediate_danger;
          return (
            <div
              className="w-full rounded-md py-2.5 text-center text-sm font-semibold transition-colors"
              style={{
                backgroundColor: isDanger ? "#e76f51" : "#2a9d8f",
                color: "#ffffff",
              }}
            >
              {isDanger ? "IMMEDIATE DANGER DETECTED" : "No Immediate Danger"}
            </div>
          );
        })()}

        {/* Location */}
        <div className="flex items-start justify-between gap-3">
          <span className="text-xs font-medium shrink-0">Extracted Location</span>
          <span className="text-xs text-right text-muted-foreground">
            {analysis.location ?? "Not identified"}
          </span>
        </div>

        {/* Summary */}
        <div className="rounded-md p-3" style={{ backgroundColor: "#f8f9fa", color: "#374151" }}>
          <div className="text-[11px] font-semibold uppercase tracking-wider mb-1" style={{ color: "#6b7280" }}>Summary</div>
          <p className="text-sm italic">{analysis.summary}</p>
        </div>

        {/* Dispatcher action */}
        <div className="rounded-md p-3" style={{ backgroundColor: "#e8f4fd", color: "#1d3557" }}>
          <div className="text-[11px] font-bold uppercase tracking-wider mb-1" style={{ color: "#1d3557" }}>Recommended Action</div>
          <p className="text-sm">{analysis.action}</p>
        </div>

        {/* Send Help */}
        <button
          type="button"
          disabled={dispatched}
          onClick={() => handleSendHelp(false)}
          className="w-full rounded-md py-4 text-base font-bold tracking-wider text-white transition-colors disabled:cursor-not-allowed"
          style={{
            backgroundColor: dispatched ? "#6b7280" : "#c1121f",
          }}
        >
          {dispatched ? "Dispatched" : "SEND HELP"}
        </button>
      </div>
    </section>
  );
}
