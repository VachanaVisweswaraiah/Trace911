import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy REST + WS to the FastAPI backend on :8000 so the app speaks to a single
// origin (and the Lovable export will work the same way without CORS surgery).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/health": { target: "http://localhost:8000", changeOrigin: true },
      "/ws": { target: "ws://localhost:8000", ws: true, changeOrigin: true },
    },
  },
});
