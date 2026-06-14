import { el } from "./dom.js";
import { renderMarkdown } from "./markdown.js";
import { setupResizablePanel } from "./resizable-panel.js";

/* ------------------------------------------------------------------ */
/* Assistant: SSE chat with a live activity ledger                     */
/* ------------------------------------------------------------------ */

const chatColumn = document.getElementById("chat-column");
const chatScroll = document.getElementById("chat-scroll");
const composer = document.getElementById("composer");
export const composerInput = document.getElementById("composer-input");
const composerSend = document.getElementById("composer-send");
const composerSendLabel = document.getElementById("composer-send-label");
const composerAttach = document.getElementById("composer-attach");
const composerAssetSelect = document.getElementById("composer-asset");
const composerFileInput = document.getElementById("composer-file-input");
const attachmentsBar = document.getElementById("attachments");
const quickActions = document.querySelectorAll(".quick-action");
const activityPanel = document.getElementById("activity-panel");
const activityResizer = document.getElementById("activity-resizer");
const activityList = document.getElementById("activity-list");
const activityLive = document.getElementById("activity-live");

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
/* Attachments: upload files and tag them to an asset                 */
/* ------------------------------------------------------------------ */

let pendingAttachments = [];

export async function loadAssetOptions() {
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

function setComposerRunning(running) {
  composerSend.classList.toggle("is-stop", running);
  composerSendLabel.textContent = running ? "Stop" : "Send";
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

  if (selectedAsset) {
    for (const attachment of attachments) {
      if (attachment.assetId) continue;
      try {
        const response = await fetch("/api/uploads/assign", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: attachment.name, asset_id: selectedAsset }),
        });
        if (response.ok) {
          const payload = await response.json();
          attachment.name = payload.name;
          attachment.assetId = payload.asset_id || "";
        }
      } catch (error) {
        // Best-effort; the file stays in the generic uploads folder.
      }
    }
  }

  const unassignedAttachments = attachments.filter((a) => !a.assetId).map((a) => a.name);

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
      body: JSON.stringify({ message: outgoingMessage, attachments: unassignedAttachments }),
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
      const answerNode = el("div", "msg-answer markdown-body");
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

export function initChat() {
  setupResizablePanel({
    resizer: activityResizer,
    panel: activityPanel,
    storageKey: "assetos.activityPanelWidth",
    min: 240,
    maxRatio: 0.8,
    invert: true,
  });

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
}
