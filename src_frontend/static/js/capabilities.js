import { el } from "./dom.js";

/* ------------------------------------------------------------------ */
/* Capabilities                                                        */
/* ------------------------------------------------------------------ */

const capTabs = document.querySelectorAll(".cap-tab");
const capPanels = {
  skills: document.getElementById("cap-panel-skills"),
  tools: document.getElementById("cap-panel-tools"),
};
const skillsList = document.getElementById("skills-list");
const toolsList = document.getElementById("tools-list");
const skillForm = document.getElementById("skill-form");

function capToggle(checked, onChange) {
  const label = el("label", "cap-toggle");
  const input = el("input");
  input.type = "checkbox";
  input.checked = checked;
  input.addEventListener("change", () => onChange(input.checked));
  label.appendChild(input);
  label.appendChild(el("span", "cap-toggle-track"));
  return label;
}

export async function loadCapabilities() {
  const response = await fetch("/api/capabilities");
  const { tools, skills } = await response.json();

  skillsList.replaceChildren();
  if (!skills.length) {
    skillsList.appendChild(el("p", "view-lede", "No skills found yet."));
  }
  for (const skill of skills) {
    const row = el("div", "cap-row");
    const body = el("div", "cap-row-body");
    body.appendChild(el("div", "cap-row-name", skill.name));
    if (skill.summary) body.appendChild(el("p", "cap-row-desc", skill.summary));
    row.appendChild(body);
    row.appendChild(
      capToggle(skill.enabled, async (enabled) => {
        await fetch(`/api/capabilities/skills/${encodeURIComponent(skill.name)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled }),
        });
      })
    );
    skillsList.appendChild(row);
  }

  toolsList.replaceChildren();
  if (!tools.length) {
    toolsList.appendChild(el("p", "view-lede", "No tools found."));
  }
  const groups = new Map();
  for (const tool of tools) {
    const group = tool.group || "Other";
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(tool);
  }
  for (const [group, groupTools] of groups) {
    toolsList.appendChild(el("h2", "cap-group-title", group));
    for (const tool of groupTools) {
      const row = el("div", "cap-row");
      const body = el("div", "cap-row-body");
      const nameLine = el("div", "cap-row-name", tool.name);
      if (tool.requires_approval) nameLine.appendChild(el("span", "cap-tag", "Approval"));
      body.appendChild(nameLine);
      if (tool.description) body.appendChild(el("p", "cap-row-desc", tool.description));
      if (tool.args && Object.keys(tool.args).length) {
        body.appendChild(el("p", "cap-row-args", `Args: ${Object.keys(tool.args).join(", ")}`));
      }
      row.appendChild(body);
      row.appendChild(
        capToggle(tool.enabled, async (enabled) => {
          await fetch(`/api/capabilities/tools/${encodeURIComponent(tool.name)}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled }),
          });
        })
      );
      toolsList.appendChild(row);
    }
  }
}

export function initCapabilities() {
  capTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      capTabs.forEach((t) => t.classList.toggle("active", t === tab));
      for (const [name, panel] of Object.entries(capPanels)) {
        panel.hidden = name !== tab.dataset.tab;
      }
    });
  });

  skillForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = document.getElementById("skill-name").value.trim();
    const summary = document.getElementById("skill-summary").value.trim();
    const content = document.getElementById("skill-content").value.trim();
    if (!name || !content) return;
    const response = await fetch("/api/skills", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, content, summary }),
    });
    if (response.ok) {
      skillForm.reset();
      loadCapabilities();
    }
  });
}
