import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // 开发时 Vite 独立运行，/api 和 /ws 代理到 FastAPI 后端
    proxy: {
      "/api": "http://127.0.0.1:9090",
      "/ws": {
        target: "ws://127.0.0.1:9090",
        ws: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
