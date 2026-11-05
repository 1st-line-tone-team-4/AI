"""Lazy optional SDK integrations. No optional SDK is installed or contacted at import time."""

import base64
import importlib

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


class SDKClient:
    def __init__(self, provider: str, api_key: str, settings: Settings):
        if not settings.live_enabled:
            raise ConfigurationError("Provider calls are disabled by AI_LIVE_ENABLED.")
        self.provider = provider
        self.settings = settings
        try:
            sdk = importlib.import_module(provider)
        except ImportError:
            raise ConfigurationError(
                f"Install the optional {provider} SDK before enabling it."
            ) from None
        constructor = sdk.OpenAI if provider == "openai" else sdk.Anthropic
        endpoint = (
            "https://api.openai.com/v1" if provider == "openai" else "https://api.anthropic.com"
        )
        self.client = constructor(
            api_key=api_key, base_url=endpoint, timeout=settings.timeout_seconds, max_retries=0
        )

    def check_model_access(self, model: str) -> None:
        try:
            self.client.models.retrieve(model)
        except Exception as exc:
            self._error(exc)

    @staticmethod
    def _error(exc):
        code = getattr(exc, "status_code", None)
        if code == 429:
            raise RateLimitError("Provider quota exceeded; no automatic retry.") from None
        if code in (400, 401, 403, 404):
            raise ModelAccessError("Provider rejected credentials, model or schema.") from None
        if "Timeout" in type(exc).__name__:
            raise RequestTimeoutError(
                "Provider request timed out; outcome may be unknown."
            ) from None
        raise ProviderError(
            "Optional provider request failed; no raw provider response logged."
        ) from None

    def generate_json(
        self, *, model: str, prompt: str, schema: type[T], images: list[ImageInput] | None = None
    ) -> T:
        try:
            if self.provider == "openai":
                content = [{"type": "input_text", "text": prompt}]
                for image in images or []:
                    encoded = base64.b64encode(image.data).decode("ascii")
                    content.append(
                        {
                            "type": "input_image",
                            "image_url": f"data:{image.mime_type};base64,{encoded}",
                        }
                    )
                response = self.client.responses.parse(
                    model=model,
                    input=[{"role": "user", "content": content}],
                    text_format=schema,
                    max_output_tokens=self.settings.max_output_tokens,
                    store=False,
                )
                if response.status != "completed":
                    raise InvalidResponseError("OpenAI output incomplete or refused.")
                return validate_json(response.output_text, schema)
            content = [{"type": "text", "text": prompt}]
            for image in images or []:
                content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": image.mime_type,
                            "data": base64.b64encode(image.data).decode("ascii"),
                        },
                    }
                )
            response = self.client.messages.parse(
                model=model,
                max_tokens=self.settings.max_output_tokens,
                messages=[{"role": "user", "content": content}],
                output_format=schema,
            )
            if response.stop_reason != "end_turn":
                raise InvalidResponseError("Anthropic output incomplete or refused.")
            raw = "".join(block.text for block in response.content if block.type == "text")
            return validate_json(raw, schema)
        except InvalidResponseError:
            raise
        except Exception as exc:
            self._error(exc)

    def close(self):
        self.client.close()
