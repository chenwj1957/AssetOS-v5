import { el } from "./dom.js";
import { renderMarkdown } from "./markdown.js";
import { setupResizablePanel } from "./resizable-panel.js";

/* ------------------------------------------------------------------ */
/* Runs                                                                */
/* ------------------------------------------------------------------ */

const runsList = document.getElementById("runs-list");
const runDetail = document.getElementById("run-detail");
const runsResizer = document.getElementById("runs-resizer");

function renderRunsPanelEmpty() {
  runDetail.replaceChildren();
  runDetail.appendChild(el("p", "view-lede panel-empty", "Select a run from the list to see its details here."));
}

export async function loadRuns() {
  const response = await fetch("/api/runs");
  const { runs } = await response.json();
  runsList.replaceChildren();
  renderRunsPanelEmpty();
  if (!runs.length) {
    runsList.appendChild(el("p", "view-lede", "No runs yet. Every assistant or scheduled run will be journaled here."));
    return;
  }
  let activeRow = null;
  for (const run of runs) {
    const row = el("button", "run-row");
    row.appendChild(el("span", "run-name", `${run.asset || "general"} · ${run.name}`));
    row.appendChild(el("span", "run-task", run.task));
    row.addEventListener("click", async () => {
      if (activeRow) activeRow.classList.remove("active");
      activeRow = row;
      row.classList.add("active");
      const detailResponse = await fetch(`/api/runs/${encodeURIComponent(run.asset)}/${encodeURIComponent(run.name)}`);
      const payload = await detailResponse.json();
      runDetail.replaceChildren();
      runDetail.appendChild(el("div", "panel-kicker", "Run"));
      runDetail.appendChild(el("h3", "panel-title", run.name));
      if (run.name.toLowerCase().endsWith(".md")) {
        const rendered = el("div", "run-view markdown-body");
        rendered.innerHTML = renderMarkdown(payload.content);
        runDetail.appendChild(rendered);
      } else {
        runDetail.appendChild(el("pre", "run-view is-plain", payload.content));
      }
    });
    runsList.appendChild(row);
  }
}

export function initRuns() {
  setupResizablePanel({
    resizer: runsResizer,
    panel: runsList,
    storageKey: "assetos.runsListWidth",
    min: 200,
    maxRatio: 0.7,
  });
}
