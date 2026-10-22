"""Ollama HTTP client (standard library only).

The backend is the only component that talks to Ollama. The client is
deliberately narrow: it can list models and request one chat completion. It
has no access to the database and returns plain text for the service to
validate.

System proxy settings are ignored on purpose: Ollama runs locally, and a
corporate proxy must never receive (or intercept) these requests.
"""

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Protocol

from app.ai.errors import LlmModelNotFound, LlmResponseError, LlmTimeout, LlmUnavailable


class LlmClient(Protocol):
    model: str

    def list_models(self) -> list[str]: ...

    def chat(self, messages: list[dict[str, str]], response_schema: dict[str, Any]) -> str: ...


def model_is_available(model: str, available: list[str]) -> bool:
    """Ollama treats a name without a tag as ':latest'."""
    names = set(available)
    return model in names or (":" not in model and f"{model}:latest" in names)


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout_seconds: float = 180.0,
        temperature: float = 0.0,
        num_ctx: int = 8192,
        seed: int | None = 42,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.num_ctx = num_ctx
        self.seed = seed
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    # -- HTTP -----------------------------------------------------------------

    def _request(self, method: str, path: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with self._opener.open(request, timeout=timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = _error_detail(exc)
            if exc.code == 404 and "not found" in detail.lower():
                raise LlmModelNotFound(
                    f"Model '{self.model}' is not available in Ollama ({detail}). Run: ollama pull {self.model}"
                ) from exc
            raise LlmResponseError(f"Ollama returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            # urllib wraps errors raised while connecting/sending in URLError.
            # A timeout here means no connection was established (on Windows a
            # closed port can take ~2s to refuse), so Ollama is unreachable,
            # not slow.
            if isinstance(exc.reason, TimeoutError | socket.timeout):
                raise LlmUnavailable(
                    f"Cannot reach Ollama at {self.base_url}: connection timed out after {timeout:g}s"
                ) from exc
            raise LlmUnavailable(f"Cannot reach Ollama at {self.base_url}: {exc.reason}") from exc
        except TimeoutError as exc:
            # Raised unwrapped while waiting for the response: connected, but
            # the model did not finish in time.
            raise LlmTimeout(f"Ollama did not respond within {timeout:g}s") from exc
        except OSError as exc:
            raise LlmUnavailable(f"Cannot reach Ollama at {self.base_url}: {exc}") from exc

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise LlmResponseError("Ollama returned a non-JSON HTTP response") from exc
        if not isinstance(parsed, dict):
            raise LlmResponseError("Ollama returned an unexpected response shape")
        return parsed

    # -- API --------------------------------------------------------------------

    def list_models(self) -> list[str]:
        data = self._request("GET", "/api/tags", None, timeout=min(self.timeout_seconds, 10.0))
        return [m.get("name", "") for m in data.get("models", []) if isinstance(m, dict)]

    def chat(self, messages: list[dict[str, str]], response_schema: dict[str, Any]) -> str:
        options: dict[str, Any] = {"temperature": self.temperature, "num_ctx": self.num_ctx}
        if self.seed is not None:
            options["seed"] = self.seed
        data = self._request(
            "POST",
            "/api/chat",
            {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "format": response_schema,
                "options": options,
            },
            timeout=self.timeout_seconds,
        )
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise LlmResponseError("Ollama response did not contain message.content")
        return content


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - best effort only
        return exc.reason if isinstance(exc.reason, str) else ""
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "error" in parsed:
            return str(parsed["error"])
    except json.JSONDecodeError:
        pass
    return raw[:300]
