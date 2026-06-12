from __future__ import annotations

import json
from typing import Any

import requests

from src.core.errors import RoutingError


class AdapterOllama:
    """Generic connection adapter for an Ollama text generation model."""

    def __init__(self, base_url: str, model: str, timeout_seconds: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def generate(self, prompt: str, json_mode: bool = False) -> str:
        request_body: dict[str, Any] = {"model": self.model, "prompt": prompt, "stream": False}
        if json_mode:
            request_body["format"] = "json"

        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=request_body,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code == 404:
                raise RoutingError(
                    "Ollama generate endpoint was not found at "
                    f"{self.base_url}/api/generate. Confirm Ollama is running with `ollama serve`, "
                    "`DEFAULT_OLLAMA_URL` in `src.core.constants` points to the Ollama server, and no other service is bound "
                    "to that port."
                ) from exc
            raise RoutingError(f"Ollama generate request failed with HTTP {status_code}: {exc}") from exc
        except requests.RequestException as exc:
            raise RoutingError(
                "Ollama generate request failed. Confirm Ollama is running, the configured base URL "
                f"is reachable ({self.base_url}), and model '{self.model}' is installed. Original error: {exc}"
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise RoutingError(f"Ollama returned a non-JSON HTTP response: {response.text[:500]!r}") from exc
        generated = payload.get("response")
        if not isinstance(generated, str):
            raise RoutingError(f"Ollama response did not include a string 'response' field: {payload!r}")
        return generated

    def generate_json(self, prompt: str) -> dict[str, Any]:
        raw = self.generate(prompt, json_mode=True)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RoutingError(f"Ollama returned malformed JSON: {exc}. Raw response: {raw!r}") from exc
        if not isinstance(parsed, dict):
            raise RoutingError(f"Ollama JSON response must be an object. Raw response: {raw!r}")
        return parsed
