/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// The repo root is the single home for .env (shared with docker-compose), so
// point Vite's env handling there instead of the default (this directory).
const envDir = fileURLToPath(new URL("..", import.meta.url));

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // .env files are NOT in process.env while this config file runs — Vite only
  // loads them for application code, after the config is evaluated. loadEnv
  // reads them explicitly ("" = no prefix filter; shell env still wins).
  const env = loadEnv(mode, envDir, "");

  return {
    plugins: [react()],
    // Makes VITE_-prefixed vars from the root .env reach import.meta.env.
    envDir,
    server: {
      // Dev-server proxy: the page requests same-origin /api/…, Vite forwards
      // it to the backend. This avoids CORS entirely in development and
      // mirrors a production reverse proxy (nginx/ALB) fronting both apps.
      proxy: {
        "/api": {
          target: env.VITE_API_PROXY_TARGET || "http://localhost:5080",
          changeOrigin: true,
        },
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      globals: false,
      coverage: {
        provider: "v8" as const,
        include: ["src/**/*.{ts,tsx}"],
        exclude: ["src/main.tsx", "src/test/**"],
      },
    },
  };
});
