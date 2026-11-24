import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API runs on :8000; proxying avoids CORS and keeps one origin in the browser.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8000" },
  },
});
