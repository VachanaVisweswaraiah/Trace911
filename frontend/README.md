# Frontend

Minimal Vite + React (JS) sanity-check app. Confirms the backend is reachable
and the WebSocket is alive. **Replace this with the Lovable export when it
lands** — keep `vite.config.js` (the proxy) and `src/api.js` (the helpers).

## Run

The repo's `make dev` starts this together with the backend. Standalone:

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173
```

The Vite dev server proxies to the backend on `:8000`:
- `/api/*`  → REST
- `/health` → health probe
- `/ws/*`   → WebSocket (with `ws: true`)

So the frontend always speaks to its own origin and there's no CORS to fight.

## What the page does

1. `GET /health` on mount → green/red dot in the header.
2. **Start call** → `POST /api/calls`, then opens `WS /ws/calls/{id}`.
3. **Confirm breathing** → `PATCH /api/calls/{id}/incident`. The WS pushes the
   updated incident card; coverage numbers tick up.
4. **End call** → `POST /api/calls/{id}/end`, surfaces the summary.
5. The bottom panel logs every WS event (`snapshot`, `incident`, `call_ended`, …).

## When you swap in Lovable

Drop the export here (overwrites `src/`, `index.html`, etc.) and keep:

- `vite.config.js` — the proxy makes REST + WS work the same way.
- `src/api.js` — copy these helpers into the Lovable code; they match the
  contracts in `../docs/api-contracts.md`.

If Lovable ships its own Vite config, merge the `server.proxy` block in.
