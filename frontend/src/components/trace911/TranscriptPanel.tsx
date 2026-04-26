import { useEffect, useRef, useState } from "react";
import { audioBus } from "./audioBus";

const ENDPOINT = "http://localhost:5000/transcript";

type Line = { id: string; text: string };

function parseTranscript(data: unknown): string[] {
  if (typeof data === "string") {
    return data.split(/\n+/).map((l) => l.trim()).filter(Boolean);
  }
  if (Array.isArray(data)) {
    return data.map((d) => (typeof d === "string" ? d : d?.text ?? "")).filter(Boolean);
  }
  if (data && typeof data === "object") {
    const obj = data as Record<string, unknown>;
    if (Array.isArray(obj.lines)) return obj.lines.map(String);
    if (typeof obj.text === "string") {
      return obj.text.split(/\n+/).map((l) => l.trim()).filter(Boolean);
    }
  }
  return [];
}

export default function TranscriptPanel() {
  const [lines, setLines] = useState<Line[]>([]);
  const [polling, setPolling] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);
  const seenRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    const unsub = audioBus.subscribeDemo((event) => {
      if (event === "reset") {
        seenRef.current.clear();
        setLines([]);
        setPolling(false);
      } else if (event === "started") {
        seenRef.current.clear();
        setLines([]);
        setPolling(true);
      }
    });
    return () => { unsub(); };
  }, []);

  useEffect(() => {
    if (!polling) return;
    let cancelled = false;
    const fetchOnce = async () => {
      try {
        const res = await fetch(ENDPOINT);
        if (!res.ok) throw new Error("bad status");
        const data = await res.json().catch(async () => await res.text());
        const parsed = parseTranscript(data);
        if (cancelled) return;
        const fresh: Line[] = [];
        parsed.forEach((text, i) => {
          const key = `${i}:${text}`;
          if (!seenRef.current.has(key)) {
            seenRef.current.add(key);
            fresh.push({ id: `${Date.now()}-${i}`, text });
          }
        });
        if (fresh.length) setLines((prev) => [...prev, ...fresh]);
      } catch { /* ignore */ }
    };
    fetchOnce();
    const id = setInterval(fetchOnce, 2000);
    return () => { cancelled = true; clearInterval(id); };
  }, [polling]);

  useEffect(() => {
    const c = containerRef.current;
    if (c) c.scrollTop = c.scrollHeight;
  }, [lines]);

  const wordCount = lines.reduce((n, l) => n + l.text.split(/\s+/).filter(Boolean).length, 0);

  return (
    <section className="panel p-5 flex flex-col min-h-0">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold">Live Transcript</h2>
        <span className="inline-flex items-center gap-1.5 text-[10px] font-bold px-2 py-0.5 rounded-full bg-[hsl(var(--signal-red))]/10 text-[hsl(var(--signal-red))]">
          <span className="live-dot" /> LIVE
        </span>
      </div>
      <div
        ref={containerRef}
        className="flex-1 min-h-0 overflow-y-auto rounded-md bg-muted/30 border border-border p-3 font-mono text-[14px] leading-relaxed"
      >
        {lines.length === 0 ? (
          <p className="italic text-muted-foreground">Waiting for incoming call...</p>
        ) : (
          lines.map((l) => (
            <div key={l.id} className="fade-in-line py-0.5">
              {l.text}
            </div>
          ))
        )}
      </div>
      <div className="mt-3 flex items-center justify-between text-[11px] text-muted-foreground">
        <span>Powered by Gradium STT</span>
        <span>{wordCount > 0 ? `${wordCount} words transcribed` : "0 words transcribed"}</span>
      </div>
    </section>
  );
}
