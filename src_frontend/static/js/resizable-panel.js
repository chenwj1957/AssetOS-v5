/* ------------------------------------------------------------------ */
/* Shared drag-to-resize behaviour for side panels, with the width     */
/* persisted across sessions via localStorage.                        */
/* ------------------------------------------------------------------ */

export function setupResizablePanel({ resizer, panel, storageKey, min, maxRatio, invert = false }) {
  function apply(width) {
    panel.style.flexBasis = `${width}px`;
  }

  const saved = parseInt(localStorage.getItem(storageKey) || "", 10);
  if (!Number.isNaN(saved)) apply(saved);

  let dragging = false;
  let startX = 0;
  let startWidth = 0;

  resizer.addEventListener("mousedown", (event) => {
    dragging = true;
    startX = event.clientX;
    startWidth = panel.getBoundingClientRect().width;
    resizer.classList.add("is-dragging");
    document.body.style.userSelect = "none";
    event.preventDefault();
  });

  window.addEventListener("mousemove", (event) => {
    if (!dragging) return;
    const delta = invert ? startX - event.clientX : event.clientX - startX;
    const maxWidth = panel.parentElement.getBoundingClientRect().width * maxRatio;
    const width = Math.min(Math.max(startWidth + delta, min), maxWidth);
    apply(width);
  });

  window.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    resizer.classList.remove("is-dragging");
    document.body.style.userSelect = "";
    localStorage.setItem(storageKey, String(Math.round(panel.getBoundingClientRect().width)));
  });
}
