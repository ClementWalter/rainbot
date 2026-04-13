import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies every /api/* call to the FastAPI process on :8000 so the
// signed-cookie session stays same-origin.  In production the FastAPI server
// itself serves the built bundle from dist/.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: false,
      },
      "/healthz": {
        target: "http://127.0.0.1:8000",
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
