"""Check that Ollama is reachable and the configured model is installed.

Usage (from the backend/ folder, virtual environment active):
    python -m app.scripts.ai_check
"""

from app.ai.client import OllamaClient, model_is_available
from app.ai.errors import LlmError
from app.config import get_settings


def main() -> int:
    s = get_settings()
    client = OllamaClient(s.ollama_base_url, s.ollama_model, timeout_seconds=s.ollama_timeout_seconds)
    print(f"Ollama URL : {s.ollama_base_url}")
    print(f"Model      : {s.ollama_model}")
    print(f"Timeout    : {s.ollama_timeout_seconds:g}s, attempts: {s.ollama_max_attempts}")
    try:
        models = client.list_models()
    except LlmError as exc:
        print(f"RESULT     : FAIL [{exc.code}] {exc.message}")
        print("Is Ollama running? Start the Ollama app, or run: ollama serve")
        return 1

    print(f"Installed  : {', '.join(sorted(models)) or '(none)'}")
    if not model_is_available(s.ollama_model, models):
        print(f"RESULT     : FAIL [MODEL_NOT_FOUND] Run: ollama pull {s.ollama_model}")
        print("Or set LOANOPS_OLLAMA_MODEL in backend\\.env to one of the installed models.")
        return 1
    print("RESULT     : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
