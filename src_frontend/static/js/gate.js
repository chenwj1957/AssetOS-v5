/* ------------------------------------------------------------------ */
/* Gated-tools switch                                                  */
/* ------------------------------------------------------------------ */

export function initGate() {
  const gateSwitch = document.getElementById("gate-switch");
  const gateState = document.getElementById("gate-state");

  function renderGateState() {
    gateState.textContent = gateSwitch.checked ? "Gated tools allowed" : "Gated tools off";
    gateSwitch.closest(".gate-toggle").querySelector(".gate-label").textContent =
      gateSwitch.checked ? "Action mode" : "Draft mode";
  }

  fetch("/api/settings")
    .then((response) => response.json())
    .then((payload) => {
      gateSwitch.checked = payload.allow_gated;
      renderGateState();
    });

  gateSwitch.addEventListener("change", () => {
    renderGateState();
    fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ allow_gated: gateSwitch.checked }),
    });
  });
}
