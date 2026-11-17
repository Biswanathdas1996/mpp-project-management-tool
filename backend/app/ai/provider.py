"""One LLM provider interface; Ollama self-hosted and Ollama Cloud implementations.

Switchable per tenant (Tenant.ai_mode = off | self_hosted | cloud).  Self-hosted is the default for
government/restricted data; cloud calls are redacted first (see redact.py) and every call is logged.
"""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from ..config import get_settings


class AIUnavailable(Exception):
    pass


TokenCallback = Callable[[str, str], None]  # (text delta, channel: "content" | "thinking")


@dataclass
class LLMResponse:
    text: str
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    done_reason: str | None = None


class LLMProvider(ABC):
    name: str = "base"
    is_external: bool = False

    @abstractmethod
    def chat_json(self, system: str, user: str | list[dict[str, str]], schema: dict[str, Any], model: str,
                  max_tokens: int = 3072, on_token: TokenCallback | None = None) -> LLMResponse: ...

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "ok": False}


class DisabledProvider(LLMProvider):
    name = "off"

    def chat_json(self, system, user, schema, model, max_tokens=3072, on_token=None):
        raise AIUnavailable("AI is turned off for this tenant")


class OllamaProvider(LLMProvider):
    """Speaks the Ollama /api/chat protocol (identical for self-hosted and https://ollama.com)."""

    def __init__(self, base_url: str, api_key: str | None, name: str, external: bool):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.name = name
        self.is_external = external
        self.timeout = get_settings().ai_timeout_seconds

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _model_name(self, model: str) -> str:
        # Direct calls to ollama.com take the bare model name; ":cloud"/"-cloud" tags are only for
        # routing through a local Ollama.
        if self.is_external:
            for suffix in (":cloud", "-cloud"):
                if model.endswith(suffix):
                    return model[: -len(suffix)]
        return model

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            r = httpx.post(f"{self.base_url}/api/chat", json=body, headers=self._headers(), timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise AIUnavailable(f"{self.name}: {exc}") from exc
        if r.status_code != 200:
            raise AIUnavailable(f"{self.name}: HTTP {r.status_code} {r.text[:300]}")
        try:
            data = r.json()
        except ValueError as exc:
            raise AIUnavailable(f"{self.name}: non-JSON reply from Ollama: {r.text[:200]}") from exc
        if data.get("error"):
            raise AIUnavailable(f"{self.name}: {str(data['error'])[:300]}")
        return data

    def _post_streaming(self, body: dict[str, Any], on_token: TokenCallback) -> dict[str, Any]:
        """Stream NDJSON chunks from /api/chat, forwarding each content/thinking delta to ``on_token``,
        and return the same shape as a non-streamed reply (message.content/thinking + final stats)."""
        content: list[str] = []
        thinking: list[str] = []
        final: dict[str, Any] = {}
        try:
            with httpx.stream("POST", f"{self.base_url}/api/chat", json=body, headers=self._headers(),
                              timeout=self.timeout) as r:
                if r.status_code != 200:
                    raise AIUnavailable(f"{self.name}: HTTP {r.status_code} {r.read().decode(errors='replace')[:300]}")
                for line in r.iter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except ValueError:
                        continue
                    if chunk.get("error"):
                        raise AIUnavailable(f"{self.name}: {str(chunk['error'])[:300]}")
                    msg = chunk.get("message") or {}
                    for part, buf, channel in ((msg.get("thinking"), thinking, "thinking"),
                                               (msg.get("content"), content, "content")):
                        if part:
                            buf.append(part)
                            try:
                                on_token(part, channel)
                            except Exception:  # a UI callback must never break the model call
                                pass
                    if chunk.get("done"):
                        final = chunk
        except httpx.HTTPError as exc:
            raise AIUnavailable(f"{self.name}: {exc}") from exc
        final = dict(final)
        final["message"] = {"content": "".join(content), "thinking": "".join(thinking)}
        return final

    def chat_json(self, system: str, user: str | list[dict[str, str]], schema: dict[str, Any], model: str,
                  max_tokens: int = 3072, on_token: TokenCallback | None = None) -> LLMResponse:
        """``user`` is a single user message, or a user/assistant conversation (used for repair turns).
        With ``on_token`` the reply is streamed and each text delta is passed as ``on_token(delta, channel)``
        (channel is "content" or "thinking"); the return value is the same either way."""
        # The schema is sent both as the `format` constraint and in the system prompt: cloud-hosted models
        # (e.g. deepseek-v4.1-flash) do not reliably enforce `format`, and then need to see the schema.
        system = (f"{system}\n\nReturn ONE JSON object that conforms to this JSON Schema (all required keys, "
                  f"no extra commentary, do not echo the input):\n{json.dumps(schema, separators=(',', ':'))}")
        turns = [{"role": "user", "content": user}] if isinstance(user, str) else list(user)
        body: dict[str, Any] = {
            "model": self._model_name(model),
            "stream": False,
            "format": schema,  # Ollama structured outputs: constrain to the JSON schema
            "messages": [{"role": "system", "content": system}, *turns],
            "options": {"temperature": 0.1, "num_ctx": 16384, "num_predict": max_tokens},
            "keep_alive": "10m",
        }
        think = get_settings().ai_think
        if think is not None:
            body["think"] = think
        t0 = time.perf_counter()
        if on_token is None:
            data = self._post(body)
        else:
            body["stream"] = True
            data = self._post_streaming(body, on_token)
        msg = data.get("message") or {}
        text = (msg.get("content") or "").strip()
        if text.startswith("```"):  # some hosted models wrap JSON in a markdown fence
            text = text.split("\n", 1)[1] if "\n" in text else ""
            text = text.rsplit("```", 1)[0].strip()
        if not text and "{" in (msg.get("thinking") or ""):
            # Some models put the whole answer in the reasoning channel; the conformer extracts the JSON.
            text = msg["thinking"].strip()
        return LLMResponse(
            text=text,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
            done_reason=data.get("done_reason"),
        )

    def health(self) -> dict[str, Any]:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", headers=self._headers(), timeout=5)
            models = [m.get("name") for m in r.json().get("models", [])] if r.status_code == 200 else []
            return {"provider": self.name, "ok": r.status_code == 200, "models": models[:50]}
        except Exception as exc:
            return {"provider": self.name, "ok": False, "error": str(exc)[:200]}


def get_provider(mode: str) -> LLMProvider:
    s = get_settings()
    if mode == "self_hosted":
        return OllamaProvider(s.ollama_self_hosted_url, None, "self_hosted", external=False)
    if mode == "cloud":
        if not s.ollama_cloud_api_key:
            return DisabledProvider()
        return OllamaProvider(s.ollama_cloud_url, s.ollama_cloud_api_key, "cloud", external=True)
    return DisabledProvider()
