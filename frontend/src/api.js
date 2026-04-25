// Thin REST + WS helpers against the FastAPI backend.
// Vite dev server proxies /api, /health, /ws to localhost:8000.

export async function getHealth() {
  const r = await fetch("/health");
  if (!r.ok) throw new Error(`health ${r.status}`);
  return r.json();
}

export async function startCall(source = "upload") {
  const r = await fetch("/api/calls", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source }),
  });
  if (!r.ok) throw new Error(`startCall ${r.status}`);
  return r.json();
}

export async function getCall(callId) {
  const r = await fetch(`/api/calls/${callId}`);
  if (!r.ok) throw new Error(`getCall ${r.status}`);
  return r.json();
}

export async function patchIncident(callId, updates) {
  const r = await fetch(`/api/calls/${callId}/incident`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ updates }),
  });
  if (!r.ok) throw new Error(`patchIncident ${r.status}`);
  return r.json();
}

export async function endCall(callId) {
  const r = await fetch(`/api/calls/${callId}/end`, { method: "POST" });
  if (!r.ok) throw new Error(`endCall ${r.status}`);
  return r.json();
}

export function openCallSocket(callId, onMessage) {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${window.location.host}/ws/calls/${callId}`);
  ws.addEventListener("message", (e) => {
    try {
      onMessage(JSON.parse(e.data));
    } catch (err) {
      console.warn("ws parse error", err);
    }
  });
  return ws;
}
