from __future__ import annotations

import threading
from dataclasses import dataclass, field

from src.agent.approval import ApprovalGate
from src.agent.loop import AgentLoop
from src.core.text import trim_to_budget
from src.core.types import AgentState

SESSION_CONTEXT_MAX_CHARS = 4_000
ANSWER_SUMMARY_CHARS = 500


@dataclass
class Session:
    """Conversational outer loop over the inner ReAct loop.

    Each user message starts a fresh inner loop seeded with a compact
    summary of the session so far. State compounds in two places:

    - short-term: this rolling session summary (capped, oldest dropped)
    - long-term: memory itself — notes, facts, and the run journal each
      inner loop writes on completion

    so the conversation can run indefinitely without the context window
    growing without bound.
    """

    loop: AgentLoop
    exchanges: list[tuple[str, str]] = field(default_factory=list)
    active_asset: str | None = None

    def ask(
        self,
        user_task: str,
        cancel_event: threading.Event | None = None,
        approval_gate: ApprovalGate | None = None,
    ) -> AgentState:
        state = self.loop.run(
            user_task,
            session_context=self._render_context(),
            cancel_event=cancel_event,
            approval_gate=approval_gate,
        )
        # Carry the active asset forward so follow-ups stay grounded.
        if state.selected_asset:
            self.active_asset = state.selected_asset
        answer = " ".join(str(state.answer).split())[:ANSWER_SUMMARY_CHARS]
        self.exchanges.append((user_task.strip(), answer))
        return state

    def _render_context(self) -> str:
        if not self.exchanges and not self.active_asset:
            return ""
        blocks: list[str] = []
        if self.active_asset:
            blocks.append(f"Active asset from earlier in this session: {self.active_asset}")
        used = sum(len(b) for b in blocks)
        exchange_blocks = [f"Q: {task}\nA: {answer}" for task, answer in self.exchanges]
        blocks.extend(trim_to_budget(exchange_blocks, SESSION_CONTEXT_MAX_CHARS, "[earlier exchanges trimmed]", used=used))
        return "Session so far (for continuity; verify facts against memory):\n" + "\n\n".join(blocks)
