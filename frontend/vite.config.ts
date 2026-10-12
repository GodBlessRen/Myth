import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// 仅本地开发启用受控代理；正式发布的 API 请求直接进入同源 Python HTTP。
const backend = process.env.MYTH_BACKEND || "http://127.0.0.1:8000";
const proxy = {
  target: backend,
  changeOrigin: true,
  configure(server: { on: (event: string, callback: (proxyReq: { setHeader: (name: string, value: string) => void }) => void) => void }) {
    // Python 拒绝不同 Origin。仅限 127.0.0.1 Vite 开发代理，绝不用于部署环境。
    server.on("proxyReq", req => req.setHeader("Origin", backend));
  },
};
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/next/",
  server: { host: "127.0.0.1", port: 5173,
    proxy: { "/api": proxy, "/logo.svg": proxy, "/logo-dark.svg": proxy, "/logo-16.svg": proxy, "/fonts": proxy } },
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false,
    rollupOptions: { output: { entryFileNames: "workbench.js", assetFileNames: "workbench.[ext]" } } },
});
