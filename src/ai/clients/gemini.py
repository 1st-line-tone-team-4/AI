from threading import Lock

import httpx
from google import genai
from google.genai import errors, types

from ai.clients.base import ImageInput, T, validate_json
from ai.config import Settings
from ai.errors import (
    ConfigurationError,
    InvalidResponseError,
    ModelAccessError,
    ProviderError,
    RateLimitError,
    RequestTimeoutError,
)


class GeminiClient:
    def __init__(self, settings: Settings, *, request_limit: int | None = None) -> None:
        self.settings = settings
        self._sdk: genai.Client | None = None
        self._lock = Lock()
        self.request_limit = request_limit
        self.requests_sent = 0
        self.usage: list[dict] = []

    def _client(self) -> genai.Client:
        if not self.settings.live_enabled:
            raise ConfigurationError("Provider calls are disabled by AI_LIVE_ENABLED.")
        key = self.settings.gemini_api_key.get_secret_value()
        if not key.strip():
            raise ConfigurationError("GEMINI_API_KEY is missing.")
        with self._lock:
            if self._sdk is None:
                self._sdk = genai.Client(
                    vertexai=False,
                    api_key=key,
                    http_options=types.HttpOptions(
                        base_url="https://generativelanguage.googleapis.com",
                        timeout=int(self.settings.timeout_seconds * 1000),
                        retry_options=types.HttpRetryOptions(attempts=1),
                    ),
                )
        return self._sdk

    @staticmethod
    def _raise_api_error(code: int) -> None:
        if code == 429:
            raise RateLimitError(
                "Gemini quota exceeded (429); no automatic retry or fallback."
            ) from None
        if code in (400, 401, 403, 404):
            raise ModelAccessError(
                f"Gemini rejected request ({code}); check key, model access and schema support."
            ) from None
        raise ProviderError(f"Gemini request failed (HTTP {code}).") from None

    def check_model_access(self, model: str) -> None:
        client = self._client()
        try:
            client.models.get(model=model)
        except errors.APIError as exc:
            self._raise_api_error(exc.code)
        except httpx.TimeoutException:
            raise RequestTimeoutError("Gemini model access check timed out.") from None
        except httpx.RequestError:
            raise ProviderError("Gemini network error during model access check.") from None

    def generate_json(
        self, *, model: str, prompt: str, schema: type[T], images: list[ImageInput] | None = None
    ) -> T:
        client = self._client()
        with self._lock:
            if self.request_limit is not None and self.requests_sent >= self.request_limit:
                raise ConfigurationError("Explicit live request budget exhausted.")
            self.requests_sent += 1
        try:
            response = client.models.generate_content(
                model=model,
                contents=[
                    prompt,
                    *[types.Part.from_bytes(data=i.data, mime_type=i.mime_type) for i in images],
                ]
                if images
                else prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=schema.model_json_schema(),
                    max_output_tokens=self.settings.max_output_tokens,
                ),
            )
        except errors.APIError as exc:
            self._raise_api_error(exc.code)
        except httpx.TimeoutException:
            raise RequestTimeoutError("Gemini generation timed out.") from None
        except httpx.RequestError:
            raise ProviderError("Gemini network error; check connectivity.") from None
        except (ValueError, TypeError):
            raise ProviderError("Gemini could not serialize the request schema.") from None
        usage = response.usage_metadata
        if usage is not None:
            self.usage.append(
                {
                    key: value
                    for key in (
                        "prompt_token_count",
                        "candidates_token_count",
                        "thoughts_token_count",
                        "total_token_count",
                    )
                    if isinstance(value := getattr(usage, key, None), int)
                }
            )
        if response.candidates and any(
            getattr(c.finish_reason, "value", c.finish_reason) == "MAX_TOKENS"
            for c in response.candidates
        ):
            raise InvalidResponseError(
                "Response truncated; raise AI_MAX_OUTPUT_TOKENS or reduce scope."
            )
        return validate_json(response.text, schema)

    def close(self) -> None:
        if self._sdk is not None:
            self._sdk.close()
            self._sdk = None
