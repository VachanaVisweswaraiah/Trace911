import React, { useEffect, useRef, useState } from "react";
import {
  endCall,
  getHealth,
  openCallSocket,
  patchIncident,
  startCall,
} from "./api.js";

export default function App() {
  const [health, setHealth] = useState({ status: "checking" });
  const [call, setCall] = useState(null); // { call_id, started_at, ws_url }
  const [snapshot, setSnapshot] = useState(null);
  const [events, setEvents] = useState([]); // [{ t, type, payload }]
  const [wsState, setWsState] = useState("idle"); // idle | open | closed
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const wsRef = useRef(null);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch((e) => setHealth({ status: "down", error: String(e) }));
  }, []);

  function logEvent(msg) {
    setEvents((prev) => [...prev.slice(-99), msg]);
  }

  async function handleStart() {
    setBusy(true);
    setErr(null);
    try {
      const c = await startCall("upload");
      setCall(c);
      const ws = openCallSocket(c.call_id, (msg) => {
        if (msg.type === "snapshot") setSnapshot(msg.payload);
        if (msg.type === "incident") {
          setSnapshot((s) => (s ? { ...s, incident: msg.payload } : s));
        }
        logEvent(msg);
      });
      ws.addEventListener("open", () => setWsState("open"));
      ws.addEventListener("close", () => setWsState("closed"));
      wsRef.current = ws;
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirmBreathing() {
    if (!call) return;
    setBusy(true);
    try {
      await patchIncident(call.call_id, [
        {
          field: "breathing",
          value: "not breathing",
          status: "confirmed_by_operator",
        },
      ]);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleEnd() {
    if (!call) return;
    setBusy(true);
    try {
      const summary = await endCall(call.call_id);
      logEvent({ type: "summary", t: 0, payload: summary });
      wsRef.current?.close();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  const incident = snapshot?.incident;
  const breathing = incident?.breathing;

  return (
    <main>
      <header className="row" style={{ justifyContent: "space-between" }}>
        <h1>trace911 · sanity check</h1>
        <span>
          <span
            className={`dot ${health.status === "ok" ? "ok" : "bad"}`}
          />
          backend: {health.status}
        </span>
      </header>

      {err && (
        <div className="card" style={{ borderColor: "var(--bad)" }}>
          <strong style={{ color: "var(--bad)" }}>error:</strong> {err}
        </div>
      )}

      <section className="card">
        <h2>1. Call</h2>
        <div className="row">
          <button onClick={handleStart} disabled={busy || !!call}>
            Start call
          </button>
          <button
            onClick={handleConfirmBreathing}
            disabled={busy || !call || !!snapshot?.ended_at}
          >
            Confirm breathing = "not breathing"
          </button>
          <button
            onClick={handleEnd}
            disabled={busy || !call || !!snapshot?.ended_at}
          >
            End call
          </button>
        </div>
        {call && (
          <dl className="kv" style={{ marginTop: 12 }}>
            <dt>call_id</dt>
            <dd>{call.call_id}</dd>
            <dt>started_at</dt>
            <dd>{call.started_at}</dd>
            <dt>ws</dt>
            <dd>
              <span className={`dot ${wsState === "open" ? "ok" : "idle"}`} />
              {wsState}
            </dd>
          </dl>
        )}
      </section>

      <section className="card">
        <h2>2. Incident card (live)</h2>
        {!incident ? (
          <p style={{ color: "var(--muted)", margin: 0 }}>
            Start a call to populate. The card seeds 11 fields with status{" "}
            <code>missing</code>.
          </p>
        ) : (
          <dl className="kv">
            <dt>field_coverage</dt>
            <dd>{incident.field_coverage}</dd>
            <dt>confirmed_coverage</dt>
            <dd>{incident.confirmed_coverage}</dd>
            <dt>dispatch_readiness</dt>
            <dd>{incident.dispatch_readiness}</dd>
            <dt>breathing</dt>
            <dd>
              {breathing?.value ?? "—"}{" "}
              <span style={{ color: "var(--muted)" }}>
                ({breathing?.status})
              </span>
            </dd>
          </dl>
        )}
      </section>

      <section className="card">
        <h2>3. WebSocket events</h2>
        <div className="events">
          {events.length === 0 && (
            <div style={{ color: "var(--muted)" }}>(none yet)</div>
          )}
          {events.map((e, i) => (
            <div key={i}>
              <span className="t">t={Number(e.t).toFixed(2)}</span>
              <span className="type">{e.type}</span>
              {summarize(e)}
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}

function summarize(e) {
  if (e.type === "snapshot") {
    return `call_id=${e.payload.call_id}`;
  }
  if (e.type === "incident") {
    return `cov=${e.payload.field_coverage} conf=${e.payload.confirmed_coverage} disp=${e.payload.dispatch_readiness}`;
  }
  if (e.type === "summary") {
    return `unconfirmed=${e.payload.unconfirmed?.length ?? 0}`;
  }
  if (e.type === "call_ended") {
    return e.payload.summary_url ?? "";
  }
  try {
    return JSON.stringify(e.payload).slice(0, 140);
  } catch {
    return "";
  }
}
