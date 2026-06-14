import { el } from "./dom.js";
import { renderMarkdown } from "./markdown.js";

/* ------------------------------------------------------------------ */
/* Assets vault                                                        */
/* ------------------------------------------------------------------ */

const assetsPage = document.getElementById("assets-page");
const assetsList = document.getElementById("assets-list");
const assetDetail = document.getElementById("asset-detail");

export async function loadAssets() {
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
  const factsList = el("ul", "compact-list");
  let hasFactsRow = false;
  if (detail.facts.length) {
    hasFactsRow = true;
    const staleCount = detail.facts.filter((fact) => fact.stale).length;
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
    factsList.appendChild(item);
  }
  if (detail.has_profile) {
    hasFactsRow = true;
    const item = el("li");
    const row = el("button", "compact-row");
    row.appendChild(el("span", "compact-row-label", "Profile"));
    row.appendChild(el("span", "compact-row-value", "→"));
    row.addEventListener("click", async () => {
      selectRow(row);
      panel.replaceChildren();
      panel.appendChild(el("div", "panel-kicker", "Profile"));
      panel.appendChild(el("h3", "panel-title", "profile.md"));
      const body = el("div", "panel-file-content markdown-body", "Loading…");
      panel.appendChild(body);
      const fileResponse = await fetch(`/api/assets/${encodeURIComponent(detail.id)}/profile.md`);
      const payload = await fileResponse.json();
      body.innerHTML = renderMarkdown(payload.content);
    });
    item.appendChild(row);
    factsList.appendChild(item);
  }
  if (hasFactsRow) {
    factsSection.appendChild(factsList);
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
      const isTextFile = file.name.toLowerCase().endsWith(".md") || file.name.toLowerCase().endsWith(".txt");
      row.addEventListener("click", async () => {
        selectRow(row);
        panel.replaceChildren();
        panel.appendChild(el("div", "panel-kicker", "Memory file"));
        panel.appendChild(el("h3", "panel-title", file.name));
        if (!isTextFile) {
          const download = el("a", "artifact-chip panel-artifact-download", "Download");
          download.href = `/api/assets/${encodeURIComponent(detail.id)}/download/${encodeURI(file.name)}`;
          panel.appendChild(download);
          if (file.name.toLowerCase().endsWith(".pdf")) {
            const frame = el("iframe", "panel-file-frame");
            frame.src = `/api/assets/${encodeURIComponent(detail.id)}/files/${encodeURI(file.name)}/view`;
            panel.appendChild(frame);
            return;
          }
          const body = el("div", "panel-file-content markdown-body", "Loading…");
          panel.appendChild(body);
          try {
            const previewResponse = await fetch(`/api/assets/${encodeURIComponent(detail.id)}/files/${encodeURI(file.name)}/preview`);
            if (!previewResponse.ok) throw new Error(`Preview failed (${previewResponse.status}).`);
            const payload = await previewResponse.json();
            body.innerHTML = payload.html;
          } catch (error) {
            body.textContent = "Preview not available for this file. Use Download instead.";
          }
          return;
        }
        const body = el("pre", "panel-file-content is-plain", "Loading…");
        panel.appendChild(body);
        const fileResponse = await fetch(`/api/assets/${encodeURIComponent(detail.id)}/files/${encodeURI(file.name)}`);
        const payload = await fileResponse.json();
        if (file.name.toLowerCase().endsWith(".md")) {
          const rendered = el("div", "panel-file-content markdown-body");
          rendered.innerHTML = renderMarkdown(payload.content);
          body.replaceWith(rendered);
        } else {
          body.textContent = payload.content;
        }
      });
      item.appendChild(row);
      list.appendChild(item);
    }
    filesSection.appendChild(list);
  } else {
    filesSection.appendChild(el("p", "view-lede", "No memory files yet."));
  }
  main.appendChild(filesSection);

  if (detail.runs && detail.runs.length) {
    const runsSection = el("div", "detail-section");
    runsSection.appendChild(el("h2", "", "Runs"));
    const list = el("ul", "compact-list");
    for (const name of detail.runs) {
      const item = el("li");
      const row = el("button", "compact-row");
      row.appendChild(el("span", "compact-row-label", name));
      row.appendChild(el("span", "compact-row-value", "→"));
      row.addEventListener("click", async () => {
        selectRow(row);
        panel.replaceChildren();
        panel.appendChild(el("div", "panel-kicker", "Run"));
        panel.appendChild(el("h3", "panel-title", name));
        const body = el("div", "panel-file-content markdown-body", "Loading…");
        panel.appendChild(body);
        const runResponse = await fetch(`/api/runs/${encodeURIComponent(detail.id)}/${encodeURIComponent(name)}`);
        const payload = await runResponse.json();
        body.innerHTML = renderMarkdown(payload.content);
      });
      item.appendChild(row);
      list.appendChild(item);
    }
    runsSection.appendChild(list);
    main.appendChild(runsSection);
  }

  if (detail.artifacts.length) {
    const artifactSection = el("div", "detail-section");
    artifactSection.appendChild(el("h2", "", "Artifacts"));
    const list = el("ul", "compact-list");
    for (const name of detail.artifacts) {
      const item = el("li");
      const row = el("button", "compact-row");
      row.appendChild(el("span", "compact-row-label", name));
      row.appendChild(el("span", "compact-row-value", "→"));
      row.addEventListener("click", async () => {
        selectRow(row);
        panel.replaceChildren();
        panel.appendChild(el("div", "panel-kicker", "Artifact"));
        panel.appendChild(el("h3", "panel-title", name));
        const download = el("a", "artifact-chip panel-artifact-download", "Download");
        download.href = `/api/assets/${encodeURIComponent(detail.id)}/artifacts/${encodeURIComponent(name)}`;
        panel.appendChild(download);
        const body = el("div", "panel-file-content markdown-body", "Loading…");
        panel.appendChild(body);
        try {
          const previewResponse = await fetch(`/api/assets/${encodeURIComponent(detail.id)}/artifacts/${encodeURIComponent(name)}/preview`);
          if (!previewResponse.ok) throw new Error(`Preview failed (${previewResponse.status}).`);
          const payload = await previewResponse.json();
          body.innerHTML = payload.html;
        } catch (error) {
          body.textContent = "Preview not available for this file. Use Download instead.";
        }
      });
      item.appendChild(row);
      list.appendChild(item);
    }
    artifactSection.appendChild(list);
    main.appendChild(artifactSection);
  }

  layout.appendChild(main);
  layout.appendChild(panel);
  assetDetail.appendChild(layout);
}
