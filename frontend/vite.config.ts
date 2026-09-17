import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";

/* MapLibre 6 runs its tile work in a module worker that it loads from files
 * beside its own code (maplibre-gl-worker.mjs, which imports
 * maplibre-gl-shared.mjs). Bundling MapLibre into the Map chunk leaves those
 * files behind, and without them the map never finishes loading, with no
 * error. Copy them into the build next to the chunk that asks for them. */
function maplibreWorker(): Plugin {
  const dist = fileURLToPath(new URL("./node_modules/maplibre-gl/dist/", import.meta.url));
  return {
    name: "maplibre-worker",
    apply: "build",
    generateBundle() {
      for (const file of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) {
        this.emitFile({ type: "asset", fileName: `assets/${file}`, source: readFileSync(dist + file) });
      }
    },
  };
}

export default defineConfig({
  plugins: [react(), maplibreWorker()],
  server: {
    // Dev server talks to the FastAPI backend so the app never needs to know
    // whether it's running from Vite or served out of the container.
    proxy: { "/api": "http://127.0.0.1:6277" },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
