import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
export default defineConfig({
  plugins: [react()],
  base: "/app/editor/",
  build: {
    outDir: fileURLToPath(
      new URL("../backend/app/static/editor", import.meta.url),
    ),
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/app/experience_paragraphs.js": "http://127.0.0.1:8000",
    },
  },
});
