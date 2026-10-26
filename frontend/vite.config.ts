import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies /api to the local FastAPI backend.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  // assetsInlineLimit 0: emit fonts as files so the strict CSP (no data: fonts) is respected.
  build: { chunkSizeWarningLimit: 1200, assetsInlineLimit: 0 },
});
