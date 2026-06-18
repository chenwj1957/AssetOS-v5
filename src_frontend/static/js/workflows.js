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
    if (workflow.type) {
      body.appendChild(el("small", "wf-type", workflow.type.replaceAll("_", " ")));
    }
    body.appendChild(el("p", "", workflow.task));
    if (Array.isArray(workflow.steps) && workflow.steps.length) {
      const steps = el("ol", "wf-steps");
      for (const step of workflow.steps) {
        steps.appendChild(el("li", "", step));
      }
      body.appendChild(steps);
    }
    if (Array.isArray(workflow.expected_outputs) && workflow.expected_outputs.length) {
      body.appendChild(el("small", "wf-outputs", `Outputs: ${workflow.expected_outputs.join(", ")}`));
    }
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
