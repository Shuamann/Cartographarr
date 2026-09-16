import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "maplibre-gl/dist/maplibre-gl.css";
import "./theme/tokens.css";
import "./theme/app.css";

// Applied before first paint so the page never flashes the wrong theme.
const saved = localStorage.getItem("theme");
document.documentElement.dataset.theme =
  saved ?? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
