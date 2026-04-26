import { useEffect, useRef, useState } from "react";
import { Play, Square } from "lucide-react";
import Waveform from "./Waveform";
import { audioBus } from "./audioBus";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

const ORIGINAL_AUDIO = "/audio/original_audio.mp3";
const ENHANCED_AUDIO = "/audio/enhanced_audio.wav";

function PlayerRow({
  label,
  badge,
  badgeColor,
  caption,
  variant,
  color,
  src,
  fileLabel,
  buttonLabel,
  duck,
}: {
  label: string;
  badge: string;
  badgeColor: string;
  caption: string;
  variant: "raw" | "clean";
  color: string;
  src: string;
  fileLabel: string;
  buttonLabel: string;
  duck?: boolean;
}) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    const audio = new Audio(src);
    audio.addEventListener("ended", () => {
      setPlaying(false);
      if (audioBus.current === src) audioBus.setCurrent(null);
    });
    audioRef.current = audio;
    const unsub = audioBus.subscribe((c) => {
      if (c !== src && audioRef.current) {
        audioRef.current.pause();
        audioRef.current.currentTime = 0;
        setPlaying(false);
      }
    });
    const unsubCmd = audioBus.subscribeCommand((cmd) => {
      const a = audioRef.current;
      if (!a) return;
      if (cmd.src !== src) return;
      if (cmd.type === "play") {
        audioBus.setCurrent(src);
        a.currentTime = 0;
        a.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
      } else if (cmd.type === "stop") {
        a.pause();
        a.currentTime = 0;
        setPlaying(false);
        if (audioBus.current === src) audioBus.setCurrent(null);
      }
    });
    return () => {
      unsub();
      unsubCmd();
      audio.pause();
    };
  }, [src]);

  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;
    a.volume = duck ? 0.2 : 1.0;
  }, [duck]);

  const toggle = () => {
    const a = audioRef.current;
    if (!a) return;
    if (playing) {
      a.pause();
      a.currentTime = 0;
      setPlaying(false);
      audioBus.setCurrent(null);
    } else {
      audioBus.setCurrent(src);
      a.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
    }
  };

  const isRaw = variant === "raw";
  const borderClass = isRaw
    ? "border-[hsl(var(--signal-red))] text-[hsl(var(--signal-red))] hover:bg-[hsl(var(--signal-red))]/10"
    : "border-[hsl(var(--signal-green))] text-[hsl(var(--signal-green))] hover:bg-[hsl(var(--signal-green))]/10";

  return (
    <div className="flex flex-col gap-3 flex-shrink-0">
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold tracking-wider text-muted-foreground">{label}</span>
        <span
          className="text-[10px] font-bold px-1.5 py-0.5 rounded"
          style={{ backgroundColor: `${badgeColor}1A`, color: badgeColor }}
        >
          {badge}
        </span>
      </div>
      <Waveform variant={variant} color={color} />
      <p className="text-xs text-muted-foreground">{caption}</p>
      <button
        onClick={toggle}
        className={`inline-flex items-center justify-center gap-2 w-full sm:w-auto sm:self-start px-4 py-2 rounded-full border text-sm font-medium transition-colors ${borderClass}`}
      >
        {playing ? <Square className="w-3.5 h-3.5 fill-current" /> : <Play className="w-3.5 h-3.5 fill-current" />}
        {playing ? "Stop" : buttonLabel}
      </button>
    </div>
  );
}

export default function AudioPanel() {
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [ttsSpeaking, setTtsSpeaking] = useState(false);

  useEffect(() => {
    const unsub = audioBus.subscribeDemo((event) => {
      if (event === "reset") {
        audioBus.command({ type: "stop", src: ORIGINAL_AUDIO });
        audioBus.command({ type: "stop", src: ENHANCED_AUDIO });
      }
    });
    return () => { unsub(); };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const r = await fetch("http://localhost:5000/tts_status");
        if (!r.ok) throw new Error("bad status");
        const d = await r.json();
        if (cancelled) return;
        setTtsSpeaking(Boolean(d?.speaking));
      } catch { /* ignore */ }
    };
    poll();
    const id = setInterval(poll, 500);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const startDemo = async () => {
    if (starting) return;
    setStarting(true);
    // Notify listeners (e.g. analysis panel) a new demo is starting
    audioBus.emitDemo("started");
    // Stop anything else, then play enhanced immediately
    audioBus.command({ type: "play", src: ENHANCED_AUDIO });
    try {
      const r = await fetch("http://localhost:5000/start", { method: "POST" });
      if (!r.ok) throw new Error("bad status");
    } catch (e) {
      console.error("Failed to start demo call", e);
    } finally {
      setTimeout(() => setStarting(false), 800);
    }
  };

  const stopDemo = async () => {
    if (stopping) return;
    setStopping(true);
    audioBus.command({ type: "stop", src: ENHANCED_AUDIO });
    try {
      const r = await fetch("http://localhost:5000/stop", { method: "POST" });
      if (!r.ok) throw new Error("bad status");
    } catch (e) {
      console.error("Failed to stop demo call", e);
    } finally {
      setTimeout(() => setStopping(false), 800);
    }
  };

  return (
    <section className="panel p-5 flex flex-col gap-4 min-h-0 overflow-y-auto">
      <h2 className="text-sm font-semibold">Audio Signal</h2>
      <PlayerRow
        label="ORIGINAL"
        badge="RAW"
        badgeColor="#e63946"
        caption="Background noise present"
        variant="raw"
        color="#e63946"
        src={ORIGINAL_AUDIO}
        fileLabel="original_audio.mp3"
        buttonLabel="Play Original"
      />
      <div className="h-px bg-border" />
      <PlayerRow
        label="ENHANCED"
        badge="AI CLEANED"
        badgeColor="#2a9d8f"
        caption="ai-coustics noise cancellation active"
        variant="clean"
        color="#2a9d8f"
        src={ENHANCED_AUDIO}
        fileLabel="enhanced_audio.wav"
        buttonLabel="Play Enhanced"
        duck={ttsSpeaking}
      />
      <div className="h-px bg-border" />
      <div className="grid grid-cols-3 gap-3">
        <div className="flex min-w-0 flex-col gap-1.5">
          <button
            onClick={startDemo}
            disabled={starting}
            className="h-11 w-full px-4 rounded-md text-sm font-semibold bg-[hsl(var(--signal-green))] text-white hover:opacity-90 transition-opacity disabled:opacity-60"
          >
            {starting ? "Starting…" : "Demo Call"}
          </button>
          <span className="text-[9px] uppercase tracking-[0.15em] opacity-0 select-none">Production</span>
        </div>
        <div className="flex min-w-0 flex-col gap-1.5">
          <button
            onClick={stopDemo}
            disabled={stopping}
            className="h-11 w-full px-4 rounded-md text-sm font-semibold text-white hover:opacity-90 transition-opacity disabled:opacity-60"
            style={{ backgroundColor: "#4a4a4a" }}
          >
            {stopping ? "Stopping…" : "Stop"}
          </button>
          <span className="text-[9px] uppercase tracking-[0.15em] opacity-0 select-none">Production</span>
        </div>
        <TooltipProvider delayDuration={150}>
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex min-w-0 flex-col gap-1.5">
                <button
                  disabled
                  aria-disabled="true"
                  className="h-11 w-full px-4 rounded-md text-sm font-semibold bg-muted text-muted-foreground cursor-not-allowed"
                >
                  Live Call
                </button>
                <span className="text-[9px] uppercase tracking-[0.15em] text-center text-muted-foreground whitespace-nowrap">
                  Production
                </span>
              </div>
            </TooltipTrigger>
            <TooltipContent>Available in production via Telnyx.</TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>
    </section>
  );
}
