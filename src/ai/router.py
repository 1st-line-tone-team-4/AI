from collections.abc import Mapping
from contextlib import contextmanager

from pydantic import SecretStr

from ai.clients.base import LLMClient, T
from ai.clients.gemini import GeminiClient
from ai.clients.groq import GroqClient
from ai.config import Role, Settings
from ai.errors import ConfigurationError, ModelAccessError


class ModelRouter:
    def __init__(self, settings: Settings, clients: Mapping[str, LLMClient]) -> None:
        self.settings = settings
        self.clients = dict(clients)

    def generate_json(
        self,
        role: Role | str,
        *,
        prompt: str,
        schema: type[T],
        model_id: str | None = None,
        images=None,
    ) -> T:
        try:
            target = self.settings.target_for(Role(role), model_id)
        except ValueError:
            raise ConfigurationError("Unknown AI role.") from None
        client = self.clients.get(target.provider)
        if client is None:
            raise ConfigurationError("Provider is not registered or its optional SDK is missing.")
        if images and not target.supports_images:
            raise ConfigurationError("Configured model is not enabled for image input.")
        kwargs = {"model": target.model, "prompt": prompt, "schema": schema}
        if images:
            kwargs["images"] = images
        return client.generate_json(**kwargs)


def build_router(settings: Settings) -> ModelRouter:
    """Local development only. HTTP requests use request_router and a request-scoped BYOK."""
    return ModelRouter(settings, {"gemini": GeminiClient(settings), "groq": GroqClient(settings)})


@contextmanager
def request_router(settings: Settings, model_id: str, api_key: str | None):
    target = settings.target_for(Role.MATERIAL_ANALYSIS, model_id)
    if not api_key or not api_key.strip() or len(api_key) > 512:
        raise ModelAccessError("X-AI-Key is required for provider calls.")
    # Never fall back to the server's development key for an HTTP request.
    key_field = "groq_api_key" if target.provider == "groq" else "gemini_api_key"
    local = settings.model_copy(update={key_field: SecretStr(api_key)})
    if target.provider == "gemini":
        client = GeminiClient(local)
    elif target.provider == "groq":
        client = GroqClient(local)
    else:
        from ai.clients.optional import SDKClient

        client = SDKClient(target.provider, api_key, local)
    try:
        yield ModelRouter(local, {target.provider: client})
    finally:
        client.close()
