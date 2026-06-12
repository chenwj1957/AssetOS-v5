"use strict";

/* ------------------------------------------------------------------ */
/* View routing                                                        */
/* ------------------------------------------------------------------ */

const VIEWS = ["assistant", "assets", "workflows", "runs"];

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
}

window.addEventListener("hashchange", () => showView(location.hash.slice(1)));

/* ------------------------------------------------------------------ */
/* Gated-tools switch                                                  */
/* ------------------------------------------------------------------ */

const gateSwitch = document.getElementById("gate-switch");

async function initGate() {
  const response = await fetch("/api/settings");
  const payload = await response.json();
  gateSwitch.checked = payload.allow_gated;
}

gateSwitch.addEventListener("change", () => {
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
const composerAttach = document.getElementById("composer-attach");
const composerAssetSelect = document.getElementById("composer-asset");
const composerFileInput = document.getElementById("composer-file-input");
const attachmentsBar = document.getElementById("attachments");

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function scrollToBottom() {
  chatScroll.scrollTop = chatScroll.scrollHeight;
}

/* ------------------------------------------------------------------ */
/* Attachments: upload files and tag them to an asset                 */
/* ------------------------------------------------------------------ */

let pendingAttachments = [];

async function loadAssetOptions() {
  try {
    const response = await fetch("/api/assets");
    const { assets } = await response.json();
    const current = composerAssetSelect.value;
    const noAssetOption = el("option", "", "No asset");
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

async function sendMessage(message) {
  const empty = document.getElementById("chat-empty");
  if (empty) empty.remove();

  const attachments = pendingAttachments.filter((a) => a.status === "done");
  let outgoingMessage = message;
  if (attachments.length) {
    const note = attachments
      .map((a) => (a.assetId ? `${a.name} (asset: ${a.assetId})` : a.name))
      .join(", ");
    outgoingMessage = `${message}\n\n[Attached file(s): ${note}]`;
  }
  pendingAttachments = [];
  renderAttachments();

  const userMsg = el("div", "msg msg-user");
  userMsg.appendChild(el("div", "msg-body", message));
  if (attachments.length) {
    const chips = el("div", "msg-attachments");
    for (const a of attachments) {
      chips.appendChild(el("span", "msg-attachment-chip", a.assetId ? `${a.name} → ${a.assetId}` : a.name));
    }
    userMsg.appendChild(chips);
  }
  chatColumn.appendChild(userMsg);

  const agentMsg = el("div", "msg msg-agent");
  const ledger = el("div", "ledger");
  agentMsg.appendChild(ledger);
  chatColumn.appendChild(agentMsg);
  scrollToBottom();

  composerSend.disabled = true;
  let entryNumber = 0;

  const addLedgerRow = (text, live) => {
    entryNumber += 1;
    const row = el("div", "ledger-row" + (live ? " ledger-live" : ""));
    row.appendChild(el("span", "ledger-no", String(entryNumber)));
    row.appendChild(el("span", "ledger-text", text));
    ledger.appendChild(row);
    scrollToBottom();
  };

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
    composerSend.disabled = false;
    composerInput.focus();
  }

  function handleEvent(event) {
    if (event.type === "event") {
      addLedgerRow(event.text.trim(), true);
      return;
    }
    if (event.type === "error") {
      agentMsg.appendChild(el("div", "msg-answer msg-error", event.text));
      scrollToBottom();
      return;
    }
    if (event.type === "final") {
      ledger.querySelectorAll(".ledger-row").forEach((row) => row.classList.remove("ledger-live"));
      agentMsg.appendChild(el("div", "msg-answer", event.answer));
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
  const message = composerInput.value.trim();
  if (!message || composerSend.disabled) return;
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

const assetsList = document.getElementById("assets-list");
const assetDetail = document.getElementById("asset-detail");

async function loadAssets() {
  assetDetail.hidden = true;
  assetsList.hidden = false;
  const response = await fetch("/api/assets");
  const { assets } = await response.json();
  assetsList.replaceChildren();
  if (!assets.length) {
    assetsList.appendChild(el("p", "view-lede", "No assets yet. Ask the assistant to create one — e.g. \u201cCreate an asset for 12 Ocean St\u201d."));
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

async function openAsset(assetId) {
  const response = await fetch(`/api/assets/${encodeURIComponent(assetId)}`);
  const detail = await response.json();
  assetsList.hidden = true;
  assetDetail.hidden = false;
  assetDetail.replaceChildren();

  const back = el("button", "detail-back", "\u2190 All assets");
  back.addEventListener("click", loadAssets);
  assetDetail.appendChild(back);
  assetDetail.appendChild(el("h2", "view-title", detail.id));

  const factsSection = el("div", "detail-section");
  factsSection.appendChild(el("h2", "", "Facts"));
  if (detail.facts.length) {
    const table = el("table", "facts");
    for (const fact of detail.facts) {
      const row = el("tr");
      row.appendChild(el("td", "", fact.field));
      const valueCell = el("td", "f-value", String(fact.value));
      if (fact.stale) valueCell.appendChild(el("span", "badge-stale", "STALE"));
      row.appendChild(valueCell);
      row.appendChild(el("td", "f-source", fact.source || ""));
      table.appendChild(row);
    }
    factsSection.appendChild(table);
  } else {
    factsSection.appendChild(el("p", "view-lede", "No facts extracted yet. Ask the assistant to extract facts for this asset."));
  }
  assetDetail.appendChild(factsSection);

  const filesSection = el("div", "detail-section");
  filesSection.appendChild(el("h2", "", "Memory files"));
  const fileView = el("div", "file-view");
  fileView.hidden = true;
  for (const file of detail.files) {
    const link = el("button", "file-link", file.name);
    link.addEventListener("click", async () => {
      const fileResponse = await fetch(`/api/assets/${encodeURIComponent(detail.id)}/files/${encodeURI(file.name)}`);
      const payload = await fileResponse.json();
      fileView.textContent = payload.content;
      fileView.hidden = false;
    });
    filesSection.appendChild(link);
  }
  filesSection.appendChild(fileView);
  assetDetail.appendChild(filesSection);

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
    assetDetail.appendChild(artifactSection);
  }
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

async function loadRuns() {
  runDetail.hidden = true;
  const response = await fetch("/api/runs");
  const { runs } = await response.json();
  runsList.replaceChildren();
  if (!runs.length) {
    runsList.appendChild(el("p", "view-lede", "No runs yet. Every assistant or scheduled run will be journaled here."));
    return;
  }
  for (const run of runs) {
    const row = el("button", "run-row");
    row.appendChild(el("span", "run-name", `${run.asset || "general"} \u00b7 ${run.name}`));
    row.appendChild(el("span", "run-task", run.task));
    row.addEventListener("click", async () => {
      const detailResponse = await fetch(`/api/runs/${encodeURIComponent(run.asset)}/${encodeURIComponent(run.name)}`);
      const payload = await detailResponse.json();
      runDetail.replaceChildren();
      const view = el("div", "run-view", payload.content);
      runDetail.appendChild(view);
      runDetail.hidden = false;
      runDetail.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
    runsList.appendChild(row);
  }
}

/* ------------------------------------------------------------------ */

initGate();
loadAssetOptions();
showView(location.hash.slice(1) || "assistant");
