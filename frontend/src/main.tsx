import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./theme/tokens.css";
import "./theme/app.css";
import { applyAccent } from "./theme/accent";

// Applied before first paint so the page never flashes the wrong theme, or
// the wrong colour: both are remembered from last time and confirmed by the
// first answer from the server.
const saved = localStorage.getItem("theme");
document.documentElement.dataset.theme =
  saved ?? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
applyAccent(localStorage.getItem("accent"));

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
