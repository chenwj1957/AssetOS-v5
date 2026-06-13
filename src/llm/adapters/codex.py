from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

from src.core.errors import LLMProviderError, RoutingError

TIMELINE_PREVIEW_CHARS = 400
_URL_RE = re.compile(r"https?://\S+")


@dataclass
class CodexResult:
    return_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass
class AgenticResult:
    """Outcome of a Codex agentic (computer-use) delegation.

    ``text`` is the agent's final reply, fed back to the controller as the
    tool observation. ``timeline`` is the step-by-step trace (searches,
    commands/navigation, messages with citations) parsed from Codex's
    ``--json`` event stream, for display in the UI. Empty when the
    underlying Codex CLI didn't emit JSONL events (older CLI versions).
    """

    text: str
    timeline: list[dict[str, Any]] = field(default_factory=list)


def _timeline_entry(item: dict[str, Any]) -> dict[str, Any] | None:
    item_type = item.get("type")
    if item_type == "web_search":
        return {"kind": "search", "query": str(item.get("query", ""))}
    if item_type == "command_execution":
        command = str(item.get("command", ""))
        is_navigation = any(token in command for token in ("curl", "wget", "http://", "https://"))
        entry: dict[str, Any] = {"kind": "navigation" if is_navigation else "command", "command": command}
        output = str(item.get("aggregated_output", "")).strip()
        if output:
            entry["output"] = output[:TIMELINE_PREVIEW_CHARS]
        return entry
    if item_type == "agent_message":
        text = str(item.get("text", "")).strip()
        if not text:
            return None
        entry = {"kind": "message", "text": text[:TIMELINE_PREVIEW_CHARS]}
        citations = sorted(set(_URL_RE.findall(text)))
        if citations:
            entry["citations"] = citations
        return entry
    if item_type == "file_change":
        paths = [c.get("path") for c in item.get("changes", []) if isinstance(c, dict) and c.get("path")]
        if paths:
            return {"kind": "file_change", "paths": paths}
    return None


def _parse_agentic_result(stdout: str) -> AgenticResult:
    """Parse Codex's ``exec --json`` JSONL event stream into a timeline.

    Falls back to treating the raw output as the final message if it isn't
    JSONL (older Codex CLI without ``--json`` support, or a plain-text
    response).
    """
    timeline: list[dict[str, Any]] = []
    messages: list[str] = []
    saw_json_event = False

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        saw_json_event = True
        entry = _timeline_entry(item)
        if entry is not None:
            timeline.append(entry)
        if item.get("type") == "agent_message":
            text = str(item.get("text", "")).strip()
            if text:
                messages.append(text)

    if not saw_json_event:
        return AgenticResult(text=stdout.strip(), timeline=[])

    final_text = "\n\n".join(messages).strip() or stdout.strip()
    return AgenticResult(text=final_text, timeline=timeline)


class AdapterCodex:
    """Connection adapter for the local Codex CLI.

    Two modes:

    - ``generate`` / ``generate_json``: read-only, no-network one-shot
      completion. Used for the agent loop controller and structured JSON
      generation (invoice data, etc.).
    - ``run_agentic``: delegates an open-ended sub-task to Codex's own
      agent with its sandboxed computer use (shell, file access, web
      search/browsing). This is how AssetOS gets research and browsing
      capability without re-implementing browser automation from scratch.
    """

    def __init__(
        self,
        model: str | None = None,
        timeout_seconds: int = 90,
        agentic_timeout_seconds: int = 600,
        dry_run: bool = False,
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.agentic_timeout_seconds = agentic_timeout_seconds
        self.dry_run = dry_run

    # ------------------------------------------------------------------
    # One-shot completion (controller / JSON generation)
    # ------------------------------------------------------------------

    def generate(self, prompt: str) -> str:
        result = self._run(prompt, self._completion_args(), self.timeout_seconds)
        return self._unwrap(result, "Codex")

    def generate_json(self, prompt: str) -> dict[str, Any]:
        raw = self.generate(prompt)
        return _parse_json_object(raw, provider="Codex")

    # ------------------------------------------------------------------
    # Agentic delegation (computer use)
    # ------------------------------------------------------------------

    def run_agentic(
        self,
        task: str,
        *,
        sandbox: str = "workspace-write",
        enable_search: bool = True,
        working_dir: str | None = None,
        timeout_seconds: int | None = None,
    ) -> AgenticResult:
        """Hand a sub-task to the Codex agent and return its final message
        plus a step-by-step timeline (searches, navigation, citations).

        Codex runs its own multi-step loop (shell commands, file edits,
        web search/fetch) inside its sandbox. AssetOS treats the whole
        run as a single tool observation, with the timeline surfaced
        separately for the activity UI.
        """
        # `--search` is a global flag and must precede the `exec` subcommand.
        args = []
        if enable_search:
            # `--search` enables Codex's built-in web search/browsing tool.
            args.append("--search")
        # `--json` streams structured step events (searches, commands,
        # messages) as JSONL so the UI can render a clean timeline.
        args.extend(["exec", "--json", "--skip-git-repo-check", "--sandbox", sandbox])
        if working_dir:
            args.extend(["--cd", working_dir])
        args.append("-")
        result = self._run(task, args, timeout_seconds or self.agentic_timeout_seconds)
        raw = self._unwrap(result, "Codex agent")
        return _parse_agentic_result(raw)

    # ------------------------------------------------------------------

    def _completion_args(self) -> list[str]:
        # Read-only, no network: deterministic completion behaviour for
        # the loop controller so it cannot take actions on its own.
        return ["exec", "--skip-git-repo-check", "--sandbox", "read-only", "-"]

    def _unwrap(self, result: CodexResult, label: str) -> str:
        if result.return_code == 0:
            return result.stdout.strip() or f"{label} returned no text output."
        if result.return_code == 127:
            raise LLMProviderError(f"{label} is not configured because the local `codex` CLI was not found.")
        if result.timed_out:
            raise LLMProviderError(f"{label} timed out.")
        raise LLMProviderError(result.stderr.strip() or f"{label} exec failed (are you logged in with `codex login`?)")

    def _run(self, prompt: str, args: list[str], timeout_seconds: int) -> CodexResult:
        if self.dry_run:
            return CodexResult(return_code=0, stdout="DRY_RUN", stderr="")
        codex_cli = shutil.which("codex")
        if codex_cli is None:
            return CodexResult(return_code=127, stdout="", stderr="codex CLI not found")
        try:
            process = subprocess.run(
                [codex_cli, *args],
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
            )
            return CodexResult(return_code=process.returncode, stdout=process.stdout, stderr=process.stderr)
        except subprocess.TimeoutExpired as exc:
            return CodexResult(
                return_code=124,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "timeout",
                timed_out=True,
            )


def _parse_json_object(raw: str, provider: str) -> dict[str, Any]:
    """Parse a JSON object, tolerating markdown fences and surrounding prose."""
    candidate = raw.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        if candidate.lower().startswith("json"):
            candidate = candidate[4:]
        candidate = candidate.strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end <= start:
            raise RoutingError(f"{provider} returned malformed JSON. Raw response: {raw!r}")
        try:
            parsed = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise RoutingError(f"{provider} returned malformed JSON: {exc}. Raw response: {raw!r}") from exc
    if not isinstance(parsed, dict):
        raise RoutingError(f"{provider} JSON response must be an object. Raw response: {raw!r}")
    return parsed
