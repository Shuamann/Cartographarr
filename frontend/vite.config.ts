import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    // Dev server talks to the FastAPI backend so the app never needs to know
    // whether it's running from Vite or served out of the container.
    proxy: { "/api": "http://127.0.0.1:6277" },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
