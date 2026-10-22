"""Errors raised by LLM clients. Each carries a stable code for the API."""


class LlmError(Exception):
    code = "LLM_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class LlmUnavailable(LlmError):
    code = "OLLAMA_UNAVAILABLE"


class LlmModelNotFound(LlmError):
    code = "MODEL_NOT_FOUND"


class LlmTimeout(LlmError):
    code = "TIMEOUT"


class LlmResponseError(LlmError):
    code = "LLM_RESPONSE_ERROR"
