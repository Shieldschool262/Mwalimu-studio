import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5198,
    proxy: {
      "/api": "http://127.0.0.1:8768",
      "/health": "http://127.0.0.1:8768",
    },
  },
});
