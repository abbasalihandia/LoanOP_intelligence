import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server forwards /api/* to the FastAPI backend, so the browser
// only ever talks to one origin and the frontend never needs a hard-coded
// backend URL.
//
// 127.0.0.1 (not "localhost") is deliberate: on Windows, Node can resolve
// "localhost" to IPv6 ::1 while uvicorn listens on IPv4 127.0.0.1, which
// produces ECONNREFUSED proxy errors.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
