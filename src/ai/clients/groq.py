"""Groq OpenAI-compatible Chat API using the already installed HTTPX dependency."""

import base64
from copy import deepcopy
from threading import Lock

import httpx

from ai.clients.base import ImageInput, T, validate_json
from ai.config import Settings
from ai.errors import (
    ConfigurationError,
    InvalidResponseError,
    ModelAccessError,
    ProviderBadGatewayError,
    ProviderError,
    ProviderRequestError,
    ProviderServiceUnavailableError,
    RateLimitError,
    RequestTimeoutError,
)

STRICT_MODELS = {
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "meta-models/muse-spark-open",
}


def strict_schema(schema: dict) -> dict:
    """Adapt only the wire schema; domain models and local validation stay intact."""
    result = deepcopy(schema)

    def convert(node):
        if isinstance(node, list):
            for value in node:
                convert(value)
        elif isinstance(node, dict):
            # Format annotations (e.g. UUID) remain validated by Pydantic after decoding.
            for annotation in ("default", "format"):
                node.pop(annotation, None)
            if "oneOf" in node:
                if "discriminator" not in node:
                    raise ConfigurationError(
                        "Strict output requires a supported discriminated union."
                    )
                node["anyOf"] = node.pop("oneOf")
                node.pop("discriminator")
            if "const" in node:
                node["enum"] = [node.pop("const")]
            if node.get("type") == "object":
                if node.get("additionalProperties") not in (None, False):
                    raise ConfigurationError("Strict output requires closed objects.")
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for key, value in node.items():
                if key in {"properties", "$defs", "definitions"}:
                    for child in value.values():
                        convert(child)
                elif key in {"items", "anyOf", "allOf", "not"}:
                    convert(value)

    convert(result)
    return result


class GroqClient:
    def __init__(
        self,
        settings: Settings,
        *,
        request_limit: int | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.settings = settings
        self.request_limit = request_limit
        self.requests_sent = 0
        self.usage: list[dict] = []
        self.rate_limits: dict[str, str] = {}
        self._http: httpx.Client | None = None
        self._transport = transport
        self._lock = Lock()

    def _client(self) -> httpx.Client:
        if not self.settings.live_enabled:
            raise ConfigurationError("Provider calls are disabled by AI_LIVE_ENABLED.")
        key = self.settings.groq_api_key.get_secret_value().strip()
        if not key:
            raise ConfigurationError("GROQ_API_KEY is missing.")
        if len(key) > 512 or not key.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise ConfigurationError(
                "GROQ_API_KEY contains invalid characters or exceeds 512 bytes."
            )
        with self._lock:
            if self._http is None:
                self._http = httpx.Client(
                    base_url="https://api.groq.com/openai/v1/",
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=self.settings.timeout_seconds,
                    transport=self._transport or httpx.HTTPTransport(retries=0),
                    follow_redirects=False,
                    trust_env=False,
                )
        return self._http

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self._client().request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise RequestTimeoutError("Groq request timed out; outcome may be unknown.") from None
        except httpx.RequestError:
            raise ProviderError("Groq network request failed; no automatic retry.") from None
        for header in (
            "retry-after",
            "x-ratelimit-remaining-requests",
            "x-ratelimit-remaining-tokens",
            "x-ratelimit-reset-requests",
            "x-ratelimit-reset-tokens",
        ):
            if header in response.headers:
                self.rate_limits[header] = response.headers[header][:128]
        code = response.status_code
        if code == 429:
            raise RateLimitError(
                "Groq rate limit exceeded (HTTP 429); no automatic retry."
            ) from None
        if code == 502:
            raise ProviderBadGatewayError("Groq returned HTTP 502 Bad Gateway.") from None
        if code == 503:
            raise ProviderServiceUnavailableError(
                "Groq returned HTTP 503 Service Unavailable."
            ) from None
        if code in (408, 504):
            raise RequestTimeoutError(
                f"Groq returned HTTP {code}; outcome may be unknown."
            ) from None
        if code in (401, 403, 404):
            raise ModelAccessError(
                f"Groq rejected credentials or model access (HTTP {code})."
            ) from None
        if code in (400, 413, 422):
            if code == 400:
                try:
                    error = response.json().get("error", {})
                    message = error.get("message", "") if isinstance(error, dict) else ""
                    if (
                        error.get("param") == "response_format"
                        and isinstance(message, str)
                        and message.startswith("invalid JSON schema")
                    ):
                        message = message.replace(
                            self.settings.groq_api_key.get_secret_value(), "[REDACTED]"
                        )
                        raise ProviderRequestError(
                            "Groq rejected response schema (HTTP 400): " + message[:1000]
                        )
                except (ValueError, AttributeError):
                    pass
            raise ProviderRequestError(
                f"Groq rejected the request (HTTP {code}); check model, schema and input limits."
            ) from None
        if not 200 <= code < 300:
            raise ProviderError(
                f"Groq returned unexpected HTTP {code}; no automatic retry."
            ) from None
        try:
            data = response.json()
        except ValueError:
            raise InvalidResponseError("Groq returned a non-JSON response envelope.") from None
        if not isinstance(data, dict):
            raise InvalidResponseError("Groq returned an invalid response envelope.")
        return data

    def check_model_access(self, model: str) -> None:
        data = self._request("GET", "models")
        rows = data.get("data")
        if not isinstance(rows, list):
            raise InvalidResponseError("Groq model metadata is missing.")
        if not any(
            isinstance(row, dict) and row.get("id") == model and row.get("active") is not False
            for row in rows
        ):
            raise ModelAccessError("Requested model is not in this account's active Groq models.")

    def generate_json(
        self, *, model: str, prompt: str, schema: type[T], images: list[ImageInput] | None = None
    ) -> T:
        # Check credentials/live flag before counting or constructing a paid request.
        self._client()
        content: str | list = prompt
        if images:
            if len(images) > 3:
                raise ProviderRequestError("This development model allows at most three images.")
            content = [{"type": "text", "text": prompt}]
            encoded_size = 0
            for image in images:
                if image.mime_type not in ("image/png", "image/jpeg", "image/webp"):
                    raise ProviderRequestError("Groq image input must be PNG, JPEG or WEBP.")
                encoded = base64.b64encode(image.data).decode("ascii")
                encoded_size += len(encoded)
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{image.mime_type};base64,{encoded}",
                        },
                    }
                )
            if encoded_size > 19 * 1024 * 1024:
                raise ProviderRequestError("Encoded images exceed the Groq request size budget.")
        use_strict = self.settings.groq_strict_outputs and model in STRICT_MODELS
        wire_schema = schema.model_json_schema()
        if use_strict:
            wire_schema = strict_schema(wire_schema)
        body = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "max_completion_tokens": self.settings.max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__[:64],
                    "strict": use_strict,
                    "schema": wire_schema,
                },
            },
        }
        with self._lock:
            if self.request_limit is not None and self.requests_sent >= self.request_limit:
                raise ConfigurationError("Explicit Groq generation request budget exhausted.")
            self.requests_sent += 1
        data = self._request("POST", "chat/completions", json=body)
        usage = data.get("usage")
        if isinstance(usage, dict):
            self.usage.append(
                {
                    k: v
                    for k, v in usage.items()
                    if k in ("prompt_tokens", "completion_tokens", "total_tokens")
                    and type(v) is int
                }
            )
        choices = data.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise InvalidResponseError("Groq returned no single completion choice.")
        choice = choices[0]
        if choice.get("finish_reason") == "length":
            raise InvalidResponseError(
                "Groq output truncated; reduce scope or increase output tokens."
            )
        message = choice.get("message")
        if choice.get("finish_reason") != "stop" or not isinstance(message, dict):
            raise InvalidResponseError("Groq output incomplete, filtered or requires a tool.")
        raw = message.get("content")
        if message.get("refusal") or not isinstance(raw, str):
            raise InvalidResponseError("Groq refused or returned no usable final text.")
        return validate_json(raw, schema)

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None
