from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any

from src.core.config import Settings, load_settings
from src.core.errors import LLMProviderError, PMIntelligenceError, RoutingError
from src.core.text import truncate_text
from src.core.types import AgentState, AgentTurn, EventLog
from src.llm.client import LLMClient
from src.memory.assets import AssetRegistry, AssetWriter
from src.memory.files.reader import FileReader
from src.memory.files.registry import FileRegistry
from src.memory.facts import FactReader, FactWriter, SchemaRegistry
from src.memory.search import MemoryIndex
from src.memory.files.writer import FileWriter
from src.memory.skills import SkillReader, SkillRegistry, SkillWriter
from src.agent.approval import ApprovalGate
from src.agent.journal import write_run_journal
from src.agent.prompt import render_transcript, system_prompt
from src.tools.base import MemoryHub, ToolContext, ToolSpec
from src.tools.registry import list_tools


def _print_emit(event: dict[str, Any]) -> None:
    print(f"\n{event}", flush=True)


def _deny_all(tool_name: str, args: dict[str, Any]) -> bool:
    """Safe default: deny gated tools unless a policy explicitly approves."""
    return False


def _always_enabled(_name: str) -> bool:
    return True


class AgentLoop:
    """Observe-think-act loop.

    Replaces v4's fixed pipeline (asset resolver -> file resolver -> skill
    resolver -> 3-step plan -> executor). The controller model now sees
    every tool result and decides the next action, so it can research,
    retry, branch, and chain artifact steps on its own.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        llm_client: LLMClient | None = None,
        tools: list[ToolSpec] | None = None,
        emit: Callable[[dict[str, Any]], None] | None = None,
        approval_policy: Callable[[str, dict[str, Any]], bool] | None = None,
        tool_enabled: Callable[[str], bool] | None = None,
        skill_enabled: Callable[[str], bool] | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.llm_client = llm_client or LLMClient(self.settings)
        self.tools = tools or list_tools()
        self._tools_by_name = {tool.name: tool for tool in self.tools}
        self.emit = emit or _print_emit
        self.approval_policy = approval_policy or _deny_all
        self.tool_enabled = tool_enabled or _always_enabled
        self.skill_enabled = skill_enabled or _always_enabled

        asset_registry = AssetRegistry(settings=self.settings)
        file_registry = FileRegistry(settings=self.settings, asset_registry=asset_registry)
        skill_registry = SkillRegistry(settings=self.settings)
        schema_registry = SchemaRegistry(path=self.settings.dir_data / "memory" / "schema.json")
        fact_reader = FactReader(asset_registry=asset_registry, schema_registry=schema_registry)
        memory_index = MemoryIndex(
            db_path=self.settings.dir_data / "memory" / "index.sqlite3",
            asset_registry=asset_registry,
            global_runs_dir=self.settings.dir_data / "memory" / "runs",
        )
        self.memory = MemoryHub(
            asset_registry=asset_registry,
            asset_writer=AssetWriter(asset_registry),
            file_registry=file_registry,
            file_reader=FileReader(file_registry),
            file_writer=FileWriter(file_registry),
            skill_registry=skill_registry,
            skill_reader=SkillReader(skill_registry),
            skill_writer=SkillWriter(skill_registry),
            schema_registry=schema_registry,
            fact_reader=fact_reader,
            fact_writer=FactWriter(asset_registry=asset_registry, schema_registry=schema_registry, reader=fact_reader),
            memory_index=memory_index,
        )

    def run(
        self,
        user_task: str,
        session_context: str = "",
        cancel_event: threading.Event | None = None,
        approval_gate: ApprovalGate | None = None,
    ) -> AgentState:
        if not user_task.strip():
            raise PMIntelligenceError("User task cannot be empty.")
        state = AgentState(user_task=user_task.strip(), session_context=session_context)
        ctx = ToolContext(
            settings=self.settings,
            llm_client=self.llm_client,
            memory=self.memory,
            state=state,
            skill_enabled=self.skill_enabled,
        )
        active_tools = [tool for tool in self.tools if self.tool_enabled(tool.name)]
        base_prompt = system_prompt(active_tools, self.settings.max_iterations)

        for iteration in range(1, self.settings.max_iterations + 1):
            if cancel_event is not None and cancel_event.is_set():
                state.answer = state.answer or "Run stopped at your request before finishing."
                self._log(state, {"type": "status", "iteration": iteration, "text": "Run stopped by user."})
                return self._finish(state)

            decision = self._next_decision(base_prompt, state)
            thought = str(decision.get("thought", "")).strip()

            if "final_answer" in decision:
                state.answer = str(decision["final_answer"])
                self._log(state, {"type": "status", "iteration": iteration, "text": "Final answer ready."})
                return self._finish(state)

            action = decision.get("action")
            if not isinstance(action, dict) or not isinstance(action.get("tool"), str):
                observation = "ERROR: response must contain either final_answer or action.tool. Re-read the format rules."
                state.turns.append(AgentTurn(iteration=iteration, thought=thought, observation=observation))
                self._log(state, {"type": "status", "iteration": iteration, "text": "Malformed decision, asked agent to retry."})
                continue

            tool_name = action["tool"]
            args = action.get("args") if isinstance(action.get("args"), dict) else {}
            turn = AgentTurn(iteration=iteration, thought=thought, tool=tool_name, args=args)
            state.turns.append(turn)
            self._log(state, {
                "type": "tool_call",
                "iteration": iteration,
                "tool": tool_name,
                "args": args,
                "thought": thought,
            })

            tool = self._tools_by_name.get(tool_name)
            approved = True
            if tool is not None and tool.requires_approval and not self.approval_policy(tool_name, args):
                self._log(state, {
                    "type": "approval_request",
                    "iteration": iteration,
                    "tool": tool_name,
                    "args": args,
                })
                approved = approval_gate.wait(cancel_event) if approval_gate is not None else False
                self._log(state, {
                    "type": "approval_result",
                    "iteration": iteration,
                    "tool": tool_name,
                    "approved": approved,
                })

            turn.observation, timeline = self._execute(ctx, tool_name, args, approved=approved)
            observation_event: dict[str, Any] = {
                "type": "observation",
                "iteration": iteration,
                "tool": tool_name,
                "text": turn.observation,
                "chars": len(turn.observation),
                "ok": not turn.observation.startswith(("ERROR", "DENIED")),
            }
            if timeline:
                observation_event["timeline"] = timeline
            self._log(state, observation_event)

        state.answer = state.answer or (
            "I reached the iteration limit before finishing. Progress so far:\n"
            + "\n".join(f"- {t.tool}: {t.observation[:200]}" for t in state.turns if t.tool)
        )
        return self._finish(state)

    def _finish(self, state: AgentState) -> AgentState:
        """End-of-run reflection: persist a searchable run journal.

        Journaling is best-effort; it must never fail the run itself.
        """
        try:
            state.journal_path = write_run_journal(state, self.settings)
            if state.journal_path is not None:
                self._log(state, {"type": "status", "text": f"Run journaled to {state.journal_path}"})
        except OSError as exc:
            self._log(state, {"type": "status", "text": f"WARNING: run journal could not be written: {exc}"})
        return state

    # ------------------------------------------------------------------

    def _next_decision(self, base_prompt: str, state: AgentState) -> dict[str, Any]:
        prompt = f"{base_prompt}\n\n{render_transcript(state, self.settings.transcript_max_chars)}"
        try:
            return self.llm_client.generate_json(prompt, provider="codex")
        except RoutingError as exc:
            # One reprompt with the parse error before giving up the turn.
            retry_prompt = f"{prompt}\n\nYour previous reply was invalid JSON ({exc}). Reply with one JSON object only."
            return self.llm_client.generate_json(retry_prompt, provider="codex")

    def _execute(
        self, ctx: ToolContext, tool_name: str, args: dict[str, Any], approved: bool = True
    ) -> tuple[str, list[dict[str, Any]] | None]:
        tool = self._tools_by_name.get(tool_name)
        if tool is None:
            return f"ERROR: unknown tool '{tool_name}'. Available: {sorted(self._tools_by_name)}", None
        if not self.tool_enabled(tool_name):
            return f"ERROR: tool '{tool_name}' is currently disabled by the user.", None
        if tool.requires_approval and not approved and not self.approval_policy(tool_name, args):
            return (
                f"DENIED: '{tool_name}' requires human approval, which was not granted in this run. "
                "Adapt: use a non-gated tool, or finish with a draft/recommendation the human can action.",
                None,
            )
        try:
            result = tool.run(ctx, args)
        except (ValueError, LLMProviderError, RoutingError) as exc:
            return f"ERROR running {tool_name}: {exc}", None
        if result.structured is not None:
            ctx.state.last_structured_result = result.structured
        if result.artifact is not None:
            ctx.state.artifacts.append(result.artifact)
        observation = truncate_text(result.observation, self.settings.observation_max_chars, "\n...[observation truncated]")
        return observation, result.timeline

    def _log(self, state: AgentState, event: dict[str, Any]) -> None:
        state.event_log.append(EventLog(timestamp=datetime.now(), event_details=event))
        self.emit(event)
