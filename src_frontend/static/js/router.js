import { loadAssets } from "./assets.js";
import { loadWorkflows } from "./workflows.js";
import { loadRuns } from "./runs.js";
import { loadCapabilities } from "./capabilities.js";

/* ------------------------------------------------------------------ */
/* View routing                                                        */
/* ------------------------------------------------------------------ */

const VIEWS = ["assistant", "assets", "workflows", "runs", "capabilities"];

export function showView(name) {
  if (!VIEWS.includes(name)) name = "assistant";
  for (const view of VIEWS) {
    document.getElementById(`view-${view}`).hidden = view !== name;
  }
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === name);
  });
  if (name === "assets") loadAssets();
  if (name === "workflows") loadWorkflows();
  if (name === "runs") loadRuns();
  if (name === "capabilities") loadCapabilities();
}

window.addEventListener("hashchange", () => showView(location.hash.slice(1)));
