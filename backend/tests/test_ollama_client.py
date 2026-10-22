"""The real Ollama HTTP client against a local stub server (no Ollama needed)."""

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.ai.client import OllamaClient, model_is_available
from app.ai.errors import LlmModelNotFound, LlmResponseError, LlmTimeout, LlmUnavailable


class _StubHandler(BaseHTTPRequestHandler):
    behaviour = "ok"
    received: list[dict] = []

    def log_message(self, *args):  # keep test output quiet
        pass

    def _send(self, code: int, body: object) -> None:
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/api/tags":
            self._send(200, {"models": [{"name": "qwen2.5:7b"}, {"name": "llama3.1:latest"}]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        _StubHandler.received.append(json.loads(self.rfile.read(length)))
        behaviour = _StubHandler.behaviour
        if behaviour == "ok":
            self._send(200, {"model": "qwen2.5:7b", "message": {"role": "assistant", "content": '{"a": 1}'}, "done": True})
        elif behaviour == "missing_model":
            self._send(404, {"error": "model 'nope:1b' not found"})
        elif behaviour == "server_error":
            self._send(500, {"error": "llama runner process has terminated"})
        elif behaviour == "no_content":
            self._send(200, {"done": True})
        elif behaviour == "slow":
            time.sleep(1.5)
            self._send(200, {"message": {"content": "late"}})


@pytest.fixture
def stub():
    _StubHandler.behaviour = "ok"
    _StubHandler.received = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_chat_success_sends_schema_and_options(stub):
    client = OllamaClient(stub, "qwen2.5:7b", timeout_seconds=5)
    assert client.chat([{"role": "user", "content": "hi"}], {"type": "object"}) == '{"a": 1}'
    sent = _StubHandler.received[0]
    assert sent["model"] == "qwen2.5:7b"
    assert sent["stream"] is False
    assert sent["format"] == {"type": "object"}
    assert sent["options"]["temperature"] == 0.0


def test_list_models(stub):
    assert OllamaClient(stub, "x").list_models() == ["qwen2.5:7b", "llama3.1:latest"]


def test_model_availability_handles_latest_tag():
    assert model_is_available("llama3.1", ["llama3.1:latest"])
    assert model_is_available("qwen2.5:7b", ["qwen2.5:7b"])
    assert not model_is_available("qwen2.5:14b", ["qwen2.5:7b"])


def test_missing_model(stub):
    _StubHandler.behaviour = "missing_model"
    with pytest.raises(LlmModelNotFound) as exc_info:
        OllamaClient(stub, "nope:1b").chat([], {})
    assert "ollama pull nope:1b" in exc_info.value.message


def test_server_error(stub):
    _StubHandler.behaviour = "server_error"
    with pytest.raises(LlmResponseError) as exc_info:
        OllamaClient(stub, "x").chat([], {})
    assert "HTTP 500" in exc_info.value.message


def test_response_without_content(stub):
    _StubHandler.behaviour = "no_content"
    with pytest.raises(LlmResponseError):
        OllamaClient(stub, "x").chat([], {})


def test_timeout(stub):
    _StubHandler.behaviour = "slow"
    with pytest.raises(LlmTimeout):
        OllamaClient(stub, "x", timeout_seconds=0.3).chat([], {})


def test_unavailable():
    client = OllamaClient(f"http://127.0.0.1:{_free_port()}", "x", timeout_seconds=2)
    with pytest.raises(LlmUnavailable):
        client.list_models()
    with pytest.raises(LlmUnavailable):
        client.chat([], {})


def test_connect_phase_timeout_is_unavailable_not_timeout():
    """Windows behaviour: connecting to a closed port can time out instead of being refused."""
    import urllib.error

    client = OllamaClient("http://127.0.0.1:11434", "x", timeout_seconds=2)

    class _Opener:
        def open(self, request, timeout):
            raise urllib.error.URLError(TimeoutError("timed out"))

    client._opener = _Opener()
    with pytest.raises(LlmUnavailable) as exc_info:
        client.list_models()
    assert "connection timed out" in exc_info.value.message


def test_error_codes():
    assert (LlmUnavailable.code, LlmModelNotFound.code, LlmTimeout.code) == (
        "OLLAMA_UNAVAILABLE", "MODEL_NOT_FOUND", "TIMEOUT")
