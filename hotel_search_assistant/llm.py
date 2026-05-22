from __future__ import annotations

import json
import os
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import AssistantConfig


class LLMError(RuntimeError):
    """Raised when the configured LLM provider cannot return a response."""


class LLMClient:
    def __init__(self, config: AssistantConfig) -> None:
        self.config = config

    def complete(self, user_message: str, *, force_json: bool = False) -> str:
        provider = self.config.provider.lower()
        if provider == "ollama":
            return self._complete_ollama(user_message, force_json=force_json)
        if provider in {"openai", "openai_compatible"}:
            return self._complete_openai_compatible(user_message, force_json=force_json)

        raise LLMError(f"Unsupported provider: {self.config.provider}")

    def _complete_ollama(self, user_message: str, *, force_json: bool) -> str:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "stream": False,
            "messages": self._messages(user_message),
            "options": {
                "temperature": self.config.temperature,
                "top_p": self.config.top_p,
                "num_predict": self.config.max_tokens,
            },
        }

        if force_json:
            payload["tools"] = [self._extract_filters_tool()]

        data = self._post_json(f"{self.config.base_url}/api/chat", payload, timeout=self.config.request_timeout_seconds)
        message = data.get("message", {})
        tool_arguments = self._extract_tool_arguments(message)
        if tool_arguments is not None:
            return tool_arguments

        content = message.get("content")
        if not isinstance(content, str):
            raise LLMError("Ollama response did not contain message.content")
        return content.strip()

    def _complete_openai_compatible(self, user_message: str, *, force_json: bool) -> str:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": self._messages(user_message),
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "top_p": self.config.top_p,
            "frequency_penalty": self.config.frequency_penalty,
            "presence_penalty": self.config.presence_penalty,
        }

        if force_json:
            payload["tools"] = [self._extract_filters_tool()]
            payload["tool_choice"] = {
                "type": "function",
                "function": {"name": "extract_hotel_filters"},
            }

        headers = {}
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        data = self._post_json(
            f"{self.config.base_url}/v1/chat/completions",
            payload,
            headers=headers,
            timeout=self.config.request_timeout_seconds,
        )
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMError("OpenAI-compatible response did not contain choices")

        message = choices[0].get("message", {})
        tool_arguments = self._extract_tool_arguments(message)
        if tool_arguments is not None:
            return tool_arguments

        content = message.get("content")
        if not isinstance(content, str):
            raise LLMError("OpenAI-compatible response did not contain message.content")
        return content.strip()

    def _messages(self, user_message: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.config.system_prompt},
            {"role": "user", "content": user_message},
        ]

    def _extract_filters_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "extract_hotel_filters",
                "description": "Return hotel search fields and filters extracted from the user request.",
                "parameters": self.config.json_schema,
            },
        }

    @staticmethod
    def _extract_tool_arguments(message: dict[str, Any]) -> str | None:
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list) or not tool_calls:
            return None

        function_call = tool_calls[0].get("function", {})
        arguments = function_call.get("arguments")
        if isinstance(arguments, dict):
            return json.dumps(arguments, ensure_ascii=False)
        if isinstance(arguments, str):
            return arguments.strip()
        return None

    @staticmethod
    def _post_json(
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
        timeout: int = 300,
    ) -> dict[str, Any]:
        request_headers = {"Content-Type": "application/json", **(headers or {})}
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=request_headers,
            method="POST",
        )

        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise LLMError(f"HTTP {error.code} from LLM provider: {details}") from error
        except (TimeoutError, socket.timeout) as error:
            raise LLMError(
                f"LLM provider did not respond within {timeout} seconds. "
                "The local model may still be loading or generating. Try again, reduce max_tokens, or use a smaller Ollama model."
            ) from error
        except URLError as error:
            raise LLMError(f"Cannot connect to LLM provider at {url}: {error.reason}") from error
        except json.JSONDecodeError as error:
            raise LLMError("LLM provider returned invalid JSON over HTTP") from error
