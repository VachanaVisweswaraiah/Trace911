type Props = { variant: "raw" | "clean"; color: string };

// Build a single-period waveform path so we can repeat it seamlessly.
function buildPath(variant: "raw" | "clean", width: number, height: number) {
  const mid = height / 2;
  const points: string[] = [];
  const steps = variant === "raw" ? 80 : 60;
  for (let i = 0; i <= steps; i++) {
    const x = (i / steps) * width;
    let y: number;
    if (variant === "raw") {
      // jagged chaotic waveform with EKG spikes
      const noise = (Math.sin(i * 1.7) + Math.sin(i * 3.3) + Math.sin(i * 7.1)) * 6;
      const spike = i % 13 === 0 ? (Math.random() > 0.5 ? -22 : 22) : 0;
      y = mid + noise + spike + (Math.random() - 0.5) * 6;
    } else {
      // smooth heartbeat: gentle sine + periodic small EKG bump
      const base = Math.sin((i / steps) * Math.PI * 4) * 8;
      const beatPos = i % 20;
      let beat = 0;
      if (beatPos === 8) beat = -16;
      else if (beatPos === 9) beat = 22;
      else if (beatPos === 10) beat = -8;
      y = mid + base + beat;
    }
    points.push(`${i === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`);
  }
  return points.join(" ");
}

export default function Waveform({ variant, color }: Props) {
  const width = 600;
  const height = 90;
  const d = buildPath(variant, width, height);
  const trackClass = variant === "raw" ? "wave-track-fast" : "wave-track-smooth";

  return (
    <div className="relative w-full overflow-hidden h-[90px] rounded-md bg-muted/40">
      <div className={`flex h-full ${trackClass}`} style={{ width: "200%" }}>
        {[0, 1].map((i) => (
          <svg
            key={i}
            viewBox={`0 0 ${width} ${height}`}
            preserveAspectRatio="none"
            className="h-full"
            style={{ width: "50%" }}
          >
            <path d={d} fill="none" stroke={color} strokeWidth={1.6} strokeLinejoin="round" strokeLinecap="round" />
          </svg>
        ))}
      </div>
    </div>
  );
}
