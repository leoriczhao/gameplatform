import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev server proxies API calls to the local backend (uvicorn :8080).
// Build outputs to dist/ (served by FastAPI in production).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": { target: "http://127.0.0.1:8080", ws: true },
    },
  },
  build: {
    outDir: "dist",
    chunkSizeWarningLimit: 1200,
  },
});
