import { initGate } from "./gate.js";
import { initChat, loadAssetOptions } from "./chat.js";
import { initWorkflows } from "./workflows.js";
import { initRuns } from "./runs.js";
import { initCapabilities } from "./capabilities.js";
import { showView } from "./router.js";

initChat();
initWorkflows();
initRuns();
initCapabilities();
initGate();
loadAssetOptions();
showView(location.hash.slice(1) || "assistant");
