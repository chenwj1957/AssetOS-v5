"use strict";

/* ------------------------------------------------------------------ */
/* View routing                                                        */
/* ------------------------------------------------------------------ */

const VIEWS = ["assistant", "assets", "workflows", "runs", "capabilities"];

function showView(name) {
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

/* ------------------------------------------------------------------ */
/* Gated-tools switch                                                  */
/* ------------------------------------------------------------------ */

const gateSwitch = document.getElementById("gate-switch");
const gateState = document.getElementById("gate-state");

function renderGateState() {
  gateState.textContent = gateSwitch.checked ? "Gated tools allowed" : "Gated tools off";
  gateSwitch.closest(".gate-toggle").querySelector(".gate-label").textContent =
    gateSwitch.checked ? "Action mode" : "Draft mode";
}

async function initGate() {
  const response = await fetch("/api/settings");
  const payload = await response.json();
  gateSwitch.checked = payload.allow_gated;
  renderGateState();
}

gateSwitch.addEventListener("change", () => {
  renderGateState();
  fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ allow_gated: gateSwitch.checked }),
  });
});

/* ------------------------------------------------------------------ */
/* Assistant: SSE chat with a live activity ledger                     */
/* ------------------------------------------------------------------ */

const chatColumn = document.getElementById("chat-column");
const chatScroll = document.getElementById("chat-scroll");
const composer = document.getElementById("composer");
const composerInput = document.getElementById("composer-input");
const composerSend = document.getElementById("composer-send");
const composerSendLabel = document.getElementById("composer-send-label");
const composerSendIcon = document.getElementById("composer-send-icon");
const composerStopIcon = document.getElementById("composer-stop-icon");
const composerAttach = document.getElementById("composer-attach");
const composerAssetSelect = document.getElementById("composer-asset");
const composerFileInput = document.getElementById("composer-file-input");
const attachmentsBar = document.getElementById("attachments");
const quickActions = document.querySelectorAll(".quick-action");
const activityPanel = document.getElementById("activity-panel");
const activityResizer = document.getElementById("activity-resizer");
const activityList = document.getElementById("activity-list");
const activityLive = document.getElementById("activity-live");

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/* ------------------------------------------------------------------ */
/* Minimal markdown renderer for agent answers                        */
/* ------------------------------------------------------------------ */

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function renderInline(text) {
  let html = escapeHtml(text);
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, "<em>$1</em>");
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return html;
}

function isTableSeparator(line) {
  return /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);
}

function splitTableRow(line) {
  let trimmed = line.trim();
  if (trimmed.startsWith("|")) trimmed = trimmed.slice(1);
  if (trimmed.endsWith("|")) trimmed = trimmed.slice(0, -1);
  return trimmed.split("|").map((cell) => cell.trim());
}

function renderMarkdown(text) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const html = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.trim() === "") {
      i += 1;
      continue;
    }

    // Fenced code block
    if (line.trim().startsWith("```")) {
      const code = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        code.push(lines[i]);
        i += 1;
      }
      i += 1; // skip closing fence
      html.push(`<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`);
      continue;
    }

    // Heading
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      const level = heading[1].length;
      html.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
      i += 1;
      continue;
    }

    // Table: header row followed by separator row
    if (line.includes("|") && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
      const headerCells = splitTableRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim() !== "") {
        rows.push(splitTableRow(lines[i]));
        i += 1;
      }
      let table = "<table><thead><tr>";
      for (const cell of headerCells) table += `<th>${renderInline(cell)}</th>`;
      table += "</tr></thead><tbody>";
      for (const row of rows) {
        table += "<tr>";
        for (const cell of row) table += `<td>${renderInline(cell)}</td>`;
        table += "</tr>";
      }
      table += "</tbody></table>";
      html.push(table);
      continue;
    }

    // Unordered list
    if (/^\s*[-*]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*]\s+/, ""));
        i += 1;
      }
      html.push(`<ul>${items.map((item) => `<li>${renderInline(item)}</li>`).join("")}</ul>`);
      continue;
    }

    // Ordered list
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+[.)]\s+/, ""));
        i += 1;
      }
      html.push(`<ol>${items.map((item) => `<li>${renderInline(item)}</li>`).join("")}</ol>`);
      continue;
    }

    // Paragraph: collect consecutive non-empty, non-special lines
    const para = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].trim().startsWith("```") &&
      !/^(#{1,6})\s+/.test(lines[i]) &&
      !/^\s*[-*]\s+/.test(lines[i]) &&
      !/^\s*\d+[.)]\s+/.test(lines[i])
    ) {
      para.push(lines[i]);
      i += 1;
    }
    html.push(`<p>${para.map(renderInline).join("<br>")}</p>`);
  }

  return html.join("\n");
}

function scrollToBottom() {
  chatScroll.scrollTop = chatScroll.scrollHeight;
}

/* ------------------------------------------------------------------ */
/* Activity panel: structured tool/skill call timeline (right panel)  */
/* ------------------------------------------------------------------ */

const SKILL_TOOLS = new Set(["list_skills", "load_skill"]);
const ICON_SKILL = '<path d="M4 5.5h7v13H4zM13 5.5h7v13h-7z"/><path d="M7.5 9h0M16.5 9h0"/>';
const ICON_TOOL = '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L4 17l3 3 5.3-5.3a4 4 0 0 0 5.4-5.4l-2 2-2-1-1-2z"/>';

function activityIcon(tool) {
  const isSkill = SKILL_TOOLS.has(tool);
  const span = el("span", "activity-icon" + (isSkill ? " activity-icon-skill" : ""));
  span.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${isSkill ? ICON_SKILL : ICON_TOOL}</svg>`;
  return span;
}

function resetActivity() {
  activityList.replaceChildren(
    el("p", "activity-empty", "Tool calls and skill lookups for the current run will appear here.")
  );
}

function showActivityPanel() {
  if (!activityPanel.hidden) return;
  activityPanel.hidden = false;
  activityResizer.hidden = false;
}

function findActivityCard(step) {
  return activityList.querySelector(
    `.activity-step[data-iteration="${step.iteration}"][data-tool="${CSS.escape(step.tool)}"]`
  );
}

const TIMELINE_LABELS = {
  search: "Search",
  navigation: "Navigate",
  command: "Command",
  message: "Message",
  file_change: "Files changed",
};

function renderTimeline(timeline) {
  const wrap = el("div", "activity-timeline");
  wrap.appendChild(el("div", "panel-kicker", "Timeline"));
  for (const step of timeline) {
    const item = el("div", `activity-timeline-item activity-timeline-${step.kind}`);
    item.appendChild(el("span", "activity-timeline-kind", TIMELINE_LABELS[step.kind] || step.kind));
    if (step.kind === "search") {
      item.appendChild(el("span", "activity-timeline-text", step.query));
    } else if (step.kind === "navigation" || step.kind === "command") {
      item.appendChild(el("code", "activity-timeline-text", step.command));
      if (step.output) item.appendChild(el("pre", "activity-timeline-output", step.output));
    } else if (step.kind === "message") {
      item.appendChild(el("p", "activity-timeline-text", step.text));
      if (step.citations && step.citations.length) {
        const cites = el("div", "activity-timeline-citations");
        for (const url of step.citations) {
          const link = el("a", "activity-citation", url);
          link.href = url;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          cites.appendChild(link);
        }
        item.appendChild(cites);
      }
    } else if (step.kind === "file_change") {
      item.appendChild(el("span", "activity-timeline-text", step.paths.join(", ")));
    }
    wrap.appendChild(item);
  }
  return wrap;
}

async function respondToApproval(approved, actions) {
  actions.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  try {
    await fetch("/api/chat/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved }),
    });
  } catch (error) {
    actions.querySelectorAll("button").forEach((button) => { button.disabled = false; });
  }
}

function handleStepEvent(step) {
  showActivityPanel();
  const placeholder = activityList.querySelector(".activity-empty");
  if (placeholder) placeholder.remove();

  if (step.type === "tool_call") {
    const card = el("div", "activity-step");
    card.dataset.iteration = String(step.iteration);
    card.dataset.tool = step.tool;
    const head = el("div", "activity-step-head");
    head.appendChild(activityIcon(step.tool));
    head.appendChild(el("span", "activity-tool", step.tool));
    head.appendChild(el("span", "activity-iter", `#${step.iteration}`));
    card.appendChild(head);
    if (step.thought) card.appendChild(el("p", "activity-thought", step.thought));
    const argsText = JSON.stringify(step.args || {});
    if (argsText && argsText !== "{}") card.appendChild(el("p", "activity-args", argsText));
    activityList.appendChild(card);
  } else if (step.type === "observation") {
    const card = findActivityCard(step);
    if (step.timeline && step.timeline.length) {
      (card || activityList).appendChild(renderTimeline(step.timeline));
    }
    const details = el("details", "activity-observation" + (step.ok ? "" : " activity-observation-error"));
    details.appendChild(el("summary", "", `Result · ${step.chars} chars`));
    details.appendChild(el("pre", "activity-observation-text", step.text));
    (card || activityList).appendChild(details);
  } else if (step.type === "approval_request") {
    const card = findActivityCard(step) || activityList;
    const wrap = el("div", "activity-approval");
    wrap.appendChild(el("p", "activity-approval-note", "Requires your approval before it runs."));
    const actions = el("div", "activity-approval-actions");
    const approveBtn = el("button", "activity-approve-btn", "Approve");
    const denyBtn = el("button", "activity-deny-btn", "Deny");
    approveBtn.type = "button";
    denyBtn.type = "button";
    approveBtn.addEventListener("click", () => respondToApproval(true, actions));
    denyBtn.addEventListener("click", () => respondToApproval(false, actions));
    actions.appendChild(approveBtn);
    actions.appendChild(denyBtn);
    wrap.appendChild(actions);
    card.appendChild(wrap);
  } else if (step.type === "approval_result") {
    const card = findActivityCard(step);
    if (card) {
      const wrap = card.querySelector(".activity-approval");
      if (wrap) wrap.remove();
      card.appendChild(
        el("p", "activity-approval-result", step.approved ? "Approved — proceeding." : "Denied by user.")
      );
    }
  } else if (step.type === "status") {
    activityList.appendChild(el("div", "activity-status", step.text));
  }
  activityList.scrollTop = activityList.scrollHeight;
}

/* ------------------------------------------------------------------ */
/* Activity panel resizing (width persisted across sessions)          */
/* ------------------------------------------------------------------ */

const ACTIVITY_WIDTH_KEY = "assetos.activityPanelWidth";
const ACTIVITY_WIDTH_MIN = 240;

function applyActivityWidth(width) {
  activityPanel.style.flexBasis = `${width}px`;
}

const savedActivityWidth = parseInt(localStorage.getItem(ACTIVITY_WIDTH_KEY) || "", 10);
if (!Number.isNaN(savedActivityWidth)) {
  applyActivityWidth(savedActivityWidth);
}

(() => {
  let dragging = false;
  let startX = 0;
  let startWidth = 0;

  activityResizer.addEventListener("mousedown", (event) => {
    dragging = true;
    startX = event.clientX;
    startWidth = activityPanel.getBoundingClientRect().width;
    activityResizer.classList.add("is-dragging");
    document.body.style.userSelect = "none";
    event.preventDefault();
  });

  window.addEventListener("mousemove", (event) => {
    if (!dragging) return;
    const delta = startX - event.clientX;
    const maxWidth = activityPanel.parentElement.getBoundingClientRect().width * 0.8;
    const width = Math.min(Math.max(startWidth + delta, ACTIVITY_WIDTH_MIN), maxWidth);
    applyActivityWidth(width);
  });

  window.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    activityResizer.classList.remove("is-dragging");
    document.body.style.userSelect = "";
    localStorage.setItem(ACTIVITY_WIDTH_KEY, String(Math.round(activityPanel.getBoundingClientRect().width)));
  });
})();

/* ------------------------------------------------------------------ */
/* Attachments: upload files and tag them to an asset                 */
/* ------------------------------------------------------------------ */

let pendingAttachments = [];

async function loadAssetOptions() {
  try {
    const response = await fetch("/api/assets");
    const { assets } = await response.json();
    const current = composerAssetSelect.value;
    const noAssetOption = el("option", "", "Portfolio-wide");
    noAssetOption.value = "";
    composerAssetSelect.replaceChildren(noAssetOption);
    for (const asset of assets) {
      const option = el("option", "", asset.id);
      option.value = asset.id;
      composerAssetSelect.appendChild(option);
    }
    composerAssetSelect.value = current;
  } catch (error) {
    // Asset list is a convenience; ignore failures here.
  }
}

function renderAttachments() {
  attachmentsBar.replaceChildren();
  attachmentsBar.hidden = pendingAttachments.length === 0;
  for (const attachment of pendingAttachments) {
    const chip = el("span", "attachment-chip");
    if (attachment.status === "uploading") chip.classList.add("attachment-uploading");
    if (attachment.status === "error") chip.classList.add("attachment-error");
    chip.appendChild(el("span", "", attachment.name));
    if (attachment.assetId) {
      chip.appendChild(el("span", "attachment-asset", attachment.assetId));
    }
    if (attachment.status === "uploading") {
      chip.appendChild(el("span", "", "uploading…"));
    } else if (attachment.status === "error") {
      chip.appendChild(el("span", "", "failed"));
    }
    const remove = el("button", "attachment-remove", "×");
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove ${attachment.name}`);
    remove.addEventListener("click", () => {
      pendingAttachments = pendingAttachments.filter((a) => a !== attachment);
      renderAttachments();
    });
    chip.appendChild(remove);
    attachmentsBar.appendChild(chip);
  }
}

async function uploadFile(file, assetId) {
  const attachment = { name: file.name, assetId, status: "uploading" };
  pendingAttachments.push(attachment);
  renderAttachments();

  const formData = new FormData();
  formData.append("file", file);
  if (assetId) formData.append("asset_id", assetId);

  try {
    const response = await fetch("/api/uploads", { method: "POST", body: formData });
    if (!response.ok) throw new Error(`Upload failed (${response.status}).`);
    const payload = await response.json();
    attachment.name = payload.name;
    attachment.assetId = payload.asset_id || "";
    attachment.status = "done";
  } catch (error) {
    attachment.status = "error";
  }
  renderAttachments();
}

composerAttach.addEventListener("click", () => composerFileInput.click());

composerFileInput.addEventListener("change", () => {
  const assetId = composerAssetSelect.value;
  for (const file of composerFileInput.files) {
    uploadFile(file, assetId);
  }
  composerFileInput.value = "";
});

quickActions.forEach((action) => {
  action.addEventListener("click", () => {
    composerInput.value = action.dataset.prompt || "";
    composerInput.dispatchEvent(new Event("input"));
    composerInput.focus();
  });
});

function setComposerRunning(running) {
  composerSend.classList.toggle("is-stop", running);
  composerSendLabel.textContent = running ? "Stop" : "Send";
  composerSendIcon.hidden = running;
  composerStopIcon.hidden = !running;
}

async function stopCurrentRun() {
  try {
    await fetch("/api/chat/stop", { method: "POST" });
  } catch (error) {
    // Best-effort; the run will still finish on its own.
  }
}

async function sendMessage(message) {
  const empty = document.getElementById("chat-empty");
  if (empty) empty.remove();

  const attachments = pendingAttachments.filter((a) => a.status === "done");
  const selectedAsset = composerAssetSelect.value;
  let outgoingMessage = message;
  if (selectedAsset) {
    outgoingMessage = `${outgoingMessage}\n\n[Selected asset context: ${selectedAsset}]`;
  }
  if (attachments.length) {
    const note = attachments
      .map((a) => (a.assetId ? `${a.name} (asset: ${a.assetId})` : a.name))
      .join(", ");
    outgoingMessage = `${outgoingMessage}\n\n[Attached file(s): ${note}]`;
  }
  pendingAttachments = [];
  renderAttachments();

  const userMsg = el("div", "msg msg-user");
  userMsg.appendChild(el("div", "msg-body", message));
  if (selectedAsset || attachments.length) {
    const chips = el("div", "msg-attachments");
    if (selectedAsset) {
      chips.appendChild(el("span", "msg-attachment-chip", `Context: ${selectedAsset}`));
    }
    for (const a of attachments) {
      chips.appendChild(el("span", "msg-attachment-chip", a.assetId ? `${a.name} → ${a.assetId}` : a.name));
    }
    userMsg.appendChild(chips);
  }
  chatColumn.appendChild(userMsg);

  const agentMsg = el("div", "msg msg-agent");
  chatColumn.appendChild(agentMsg);
  scrollToBottom();

  setComposerRunning(true);
  resetActivity();
  activityLive.hidden = false;

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: outgoingMessage }),
    });
    if (!response.ok || !response.body) {
      throw new Error(`Request failed (${response.status}).`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const chunk = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        if (!chunk.startsWith("data: ")) continue;
        handleEvent(JSON.parse(chunk.slice(6)));
      }
    }
  } catch (error) {
    const failure = el("div", "msg-answer msg-error", `Connection problem: ${error.message} Check the server and try again.`);
    agentMsg.appendChild(failure);
  } finally {
    setComposerRunning(false);
    activityLive.hidden = true;
    composerInput.focus();
  }

  function handleEvent(event) {
    if (event.type === "step") {
      handleStepEvent(event.step);
      return;
    }
    if (event.type === "error") {
      agentMsg.appendChild(el("div", "msg-answer msg-error", event.text));
      scrollToBottom();
      return;
    }
    if (event.type === "final") {
      const answerNode = el("div", "msg-answer");
      answerNode.innerHTML = renderMarkdown(event.answer || "");
      agentMsg.appendChild(answerNode);
      if (event.artifacts && event.artifacts.length) {
        const artifacts = el("div", "msg-artifacts");
        for (const artifact of event.artifacts) {
          const link = el("a", "artifact-chip", `Download ${artifact.name}`);
          link.href = `/api/assets/${encodeURIComponent(artifact.asset)}/artifacts/${encodeURIComponent(artifact.name)}`;
          artifacts.appendChild(link);
        }
        agentMsg.appendChild(artifacts);
      }
      scrollToBottom();
    }
  }
}

composer.addEventListener("submit", (event) => {
  event.preventDefault();
  if (composerSend.classList.contains("is-stop")) {
    stopCurrentRun();
    return;
  }
  const message = composerInput.value.trim();
  if (!message) return;
  composerInput.value = "";
  composerInput.style.height = "auto";
  sendMessage(message);
});

composerInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    composer.requestSubmit();
  }
});

composerInput.addEventListener("input", () => {
  composerInput.style.height = "auto";
  composerInput.style.height = `${Math.min(composerInput.scrollHeight, 160)}px`;
});

/* ------------------------------------------------------------------ */
/* Assets vault                                                        */
/* ------------------------------------------------------------------ */

const assetsPage = document.getElementById("assets-page");
const assetsList = document.getElementById("assets-list");
const assetDetail = document.getElementById("asset-detail");

async function loadAssets() {
  assetDetail.hidden = true;
  assetDetail.replaceChildren();
  assetsPage.hidden = false;
  const response = await fetch("/api/assets");
  const { assets } = await response.json();
  assetsList.replaceChildren();
  if (!assets.length) {
    assetsList.appendChild(el("p", "view-lede", "No assets yet. Ask the assistant to create one — e.g. “Create an asset for 12 Ocean St”."));
    return;
  }
  for (const asset of assets) {
    const card = el("button", "asset-card");
    card.appendChild(el("h3", "", asset.id));
    card.appendChild(el("p", "", asset.profile || "No profile yet."));
    const meta = el("div", "asset-meta", `${asset.file_count} memory file${asset.file_count === 1 ? "" : "s"}`);
    if (asset.stale_facts > 0) {
      meta.appendChild(el("span", "badge-stale", `${asset.stale_facts} stale fact${asset.stale_facts === 1 ? "" : "s"}`));
    }
    card.appendChild(meta);
    card.addEventListener("click", () => openAsset(asset.id));
    assetsList.appendChild(card);
  }
}

function renderPanelEmpty(panel) {
  panel.replaceChildren();
  panel.appendChild(el("p", "view-lede panel-empty", "Select a fact or memory file from the list to see its details here."));
}

async function openAsset(assetId) {
  const response = await fetch(`/api/assets/${encodeURIComponent(assetId)}`);
  const detail = await response.json();
  assetsPage.hidden = true;
  assetDetail.hidden = false;
  assetDetail.replaceChildren();

  const back = el("button", "detail-back", "← All assets");
  back.addEventListener("click", loadAssets);
  assetDetail.appendChild(back);
  assetDetail.appendChild(el("h2", "view-title", detail.id));

  const layout = el("div", "asset-detail-layout");
  const main = el("div", "asset-detail-main");
  const panel = el("div", "asset-detail-panel");
  renderPanelEmpty(panel);

  let activeRow = null;
  const selectRow = (row) => {
    if (activeRow) activeRow.classList.remove("active");
    activeRow = row;
    if (activeRow) activeRow.classList.add("active");
  };

  const factsSection = el("div", "detail-section");
  factsSection.appendChild(el("h2", "", "Facts"));
  if (detail.facts.length) {
    const staleCount = detail.facts.filter((fact) => fact.stale).length;
    const list = el("ul", "compact-list");
    const item = el("li");
    const row = el("button", "compact-row");
    row.appendChild(el("span", "compact-row-label", "Facts"));
    const value = el("span", "compact-row-value", `${detail.facts.length} field${detail.facts.length === 1 ? "" : "s"}`);
    if (staleCount > 0) value.appendChild(el("span", "badge-stale", `${staleCount} STALE`));
    row.appendChild(value);
    row.addEventListener("click", () => {
      selectRow(row);
      panel.replaceChildren();
      panel.appendChild(el("div", "panel-kicker", "Facts"));
      panel.appendChild(el("h3", "panel-title", detail.id));
      for (const fact of detail.facts) {
        const factRow = el("div", "panel-row");
        factRow.appendChild(el("span", "panel-row-label", fact.field));
        const valueText = el("span", "panel-row-value", String(fact.value));
        if (fact.stale) valueText.appendChild(el("span", "badge-stale", "STALE"));
        factRow.appendChild(valueText);
        panel.appendChild(factRow);
      }
      if (staleCount > 0) {
        panel.appendChild(el("p", "panel-note", "Some facts' source files have changed since extraction. Ask the assistant to re-extract facts for this asset."));
      }
    });
    item.appendChild(row);
    list.appendChild(item);
    factsSection.appendChild(list);
  } else {
    factsSection.appendChild(el("p", "view-lede", "No facts extracted yet. Ask the assistant to extract facts for this asset."));
  }
  main.appendChild(factsSection);

  const filesSection = el("div", "detail-section");
  filesSection.appendChild(el("h2", "", "Memory files"));
  if (detail.files.length) {
    const list = el("ul", "compact-list");
    for (const file of detail.files) {
      const item = el("li");
      const row = el("button", "compact-row");
      row.appendChild(el("span", "compact-row-label", file.name));
      row.appendChild(el("span", "compact-row-value", "→"));
      row.addEventListener("click", async () => {
        selectRow(row);
        panel.replaceChildren();
        panel.appendChild(el("div", "panel-kicker", "Memory file"));
        panel.appendChild(el("h3", "panel-title", file.name));
        const body = el("pre", "panel-file-content", "Loading…");
        panel.appendChild(body);
        const fileResponse = await fetch(`/api/assets/${encodeURIComponent(detail.id)}/files/${encodeURI(file.name)}`);
        const payload = await fileResponse.json();
        body.textContent = payload.content;
      });
      item.appendChild(row);
      list.appendChild(item);
    }
    filesSection.appendChild(list);
  } else {
    filesSection.appendChild(el("p", "view-lede", "No memory files yet."));
  }
  main.appendChild(filesSection);

  if (detail.artifacts.length) {
    const artifactSection = el("div", "detail-section");
    artifactSection.appendChild(el("h2", "", "Artifacts"));
    const chips = el("div", "msg-artifacts");
    for (const name of detail.artifacts) {
      const chip = el("a", "artifact-chip", name);
      chip.href = `/api/assets/${encodeURIComponent(detail.id)}/artifacts/${encodeURIComponent(name)}`;
      chips.appendChild(chip);
    }
    artifactSection.appendChild(chips);
    main.appendChild(artifactSection);
  }

  layout.appendChild(main);
  layout.appendChild(panel);
  assetDetail.appendChild(layout);
}

/* ------------------------------------------------------------------ */
/* Workflows                                                           */
/* ------------------------------------------------------------------ */

const workflowsList = document.getElementById("workflows-list");
const workflowForm = document.getElementById("workflow-form");

async function loadWorkflows() {
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

async function loadRuns() {
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
    row.appendChild(el("span", "run-name", `${run.asset || "general"} \u00b7 ${run.name}`));
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
      runDetail.appendChild(el("pre", "run-view", payload.content));
    });
    runsList.appendChild(row);
  }
}

/* ------------------------------------------------------------------ */
/* Runs panel resizing (width persisted across sessions)              */
/* ------------------------------------------------------------------ */

const RUNS_WIDTH_KEY = "assetos.runsListWidth";
const RUNS_WIDTH_MIN = 200;

function applyRunsWidth(width) {
  runsList.style.flexBasis = `${width}px`;
}

const savedRunsWidth = parseInt(localStorage.getItem(RUNS_WIDTH_KEY) || "", 10);
if (!Number.isNaN(savedRunsWidth)) {
  applyRunsWidth(savedRunsWidth);
}

(() => {
  let dragging = false;
  let startX = 0;
  let startWidth = 0;

  runsResizer.addEventListener("mousedown", (event) => {
    dragging = true;
    startX = event.clientX;
    startWidth = runsList.getBoundingClientRect().width;
    runsResizer.classList.add("is-dragging");
    document.body.style.userSelect = "none";
    event.preventDefault();
  });

  window.addEventListener("mousemove", (event) => {
    if (!dragging) return;
    const delta = event.clientX - startX;
    const maxWidth = runsList.parentElement.getBoundingClientRect().width * 0.7;
    const width = Math.min(Math.max(startWidth + delta, RUNS_WIDTH_MIN), maxWidth);
    applyRunsWidth(width);
  });

  window.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    runsResizer.classList.remove("is-dragging");
    document.body.style.userSelect = "";
    localStorage.setItem(RUNS_WIDTH_KEY, String(Math.round(runsList.getBoundingClientRect().width)));
  });
})();

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

capTabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    capTabs.forEach((t) => t.classList.toggle("active", t === tab));
    for (const [name, panel] of Object.entries(capPanels)) {
      panel.hidden = name !== tab.dataset.tab;
    }
  });
});

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

async function loadCapabilities() {
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
  for (const tool of tools) {
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

/* ------------------------------------------------------------------ */

initGate();
loadAssetOptions();
showView(location.hash.slice(1) || "assistant");
