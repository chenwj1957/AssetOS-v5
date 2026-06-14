import { el } from "./dom.js";
import { composerInput } from "./chat.js";

/* ------------------------------------------------------------------ */
/* Workflows                                                           */
/* ------------------------------------------------------------------ */

const workflowsList = document.getElementById("workflows-list");
const workflowForm = document.getElementById("workflow-form");

export async function loadWorkflows() {
  const response = await fetch("/api/workflows");
  const { workflows } = await response.json();
  workflowsList.replaceChildren();
  for (const workflow of workflows) {
    const card = el("div", "wf-card");
    const body = el("div", "wf-body");
    body.appendChild(el("h3", "", workflow.name));
    body.appendChild(el("p", "", workflow.task));
    card.appendChild(body);
    const run = el("button", "wf-run", "Run");
    run.addEventListener("click", () => {
      location.hash = "assistant";
      composerInput.value = workflow.task;
      composerInput.dispatchEvent(new Event("input"));
      composerInput.focus();
    });
    card.appendChild(run);
    workflowsList.appendChild(card);
  }
}

export function initWorkflows() {
  workflowForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = document.getElementById("workflow-name").value.trim();
    const task = document.getElementById("workflow-task").value.trim();
    if (!name || !task) return;
    await fetch("/api/workflows", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, task }),
    });
    workflowForm.reset();
    loadWorkflows();
  });
}
