from __future__ import annotations

from collections.abc import Callable
from time import perf_counter
from typing import Any, Literal

from src.core.config import Settings, load_settings
from src.llm.adapters.codex import AdapterCodex
from src.llm.adapters.ollama import AdapterOllama

Provider = Literal["ollama", "codex"]


class LLMClient:
    """Role-based access to the two local providers.

    v4 dispatched on model-name string equality, which forced every
    caller to know provider model names. v5 callers ask for a provider
    role instead:

    - ``"ollama"``: fast local model for cheap JSON classification.
    - ``"codex"``:  stronger model for agent control, reasoning, and
      structured generation. Also exposes ``run_agentic`` delegation.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self.adapter_ollama = AdapterOllama(self.settings.ollama_url, self.settings.ollama_model)
        self.adapter_codex = AdapterCodex(
            self.settings.codex_model,
            agentic_timeout_seconds=self.settings.codex_agent_timeout_seconds,
        )
        self.timing_emitter: Callable[[str], None] | None = None

    def generate_text(self, prompt: str, provider: Provider = "codex") -> str:
        return self._timed(provider, "text", lambda: self._adapter(provider).generate(prompt))

    def generate_json(self, prompt: str, provider: Provider = "codex") -> dict[str, Any]:
        return self._timed(provider, "json", lambda: self._adapter(provider).generate_json(prompt))

    def run_agentic(self, task: str, **kwargs: Any) -> str:
        """Delegate a sub-task to the Codex agent (computer use)."""
        return self._timed("codex", "agentic", lambda: self.adapter_codex.run_agentic(task, **kwargs))

    def _adapter(self, provider: Provider) -> AdapterOllama | AdapterCodex:
        if provider == "ollama":
            return self.adapter_ollama
        if provider == "codex":
            return self.adapter_codex
        raise ValueError(f"Unknown LLM provider '{provider}'.")

    def _timed(self, provider: str, mode: str, call: Callable[[], Any]) -> Any:
        started_at = perf_counter()
        try:
            return call()
        finally:
            if self.timing_emitter is not None:
                elapsed = perf_counter() - started_at
                self.timing_emitter(f"[{elapsed:.2f}s | provider={provider} | mode={mode}]")
