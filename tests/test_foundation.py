from unittest.mock import MagicMock, patch

import httpx
import pytest
from google.genai import errors
from pydantic import BaseModel, ConfigDict, SecretStr

from ai.clients.base import validate_json
from ai.clients.gemini import GeminiClient
from ai.config import ModelTarget, Role, Settings
from ai.errors import (
    ConfigurationError,
    InvalidResponseError,
    ModelAccessError,
    ModelSelectionError,
    ProviderError,
    RateLimitError,
    RequestTimeoutError,
)
from ai.router import ModelRouter, build_router


class SmokeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: str


@pytest.mark.parametrize("role", list(Role))
def test_all_roles_offline(role):
    with patch("ai.clients.gemini.genai.Client", side_effect=AssertionError("network forbidden")):
        with pytest.raises((ConfigurationError, ModelSelectionError)):
            build_router(Settings()).generate_json(role, prompt="test", schema=SmokeResponse)


def test_role_override_preserves_schema():
    settings = Settings(
        model_allowlist={
            "openai:future": ModelTarget(provider="openai", model="future", available=True),
            "gemini:fixture-model": ModelTarget(
                provider="gemini", model="fixture-model", available=True
            ),
        },
        routes={Role.EVALUATION: "openai:future"},
        default_model_id="gemini:fixture-model",
    )
    fake = MagicMock()
    fake.generate_json.return_value = SmokeResponse(message="evaluated")
    router = ModelRouter(settings, {"openai": fake})
    assert (
        router.generate_json("evaluation", prompt="test", schema=SmokeResponse).message
        == "evaluated"
    )
    fake.generate_json.assert_called_once_with(model="future", prompt="test", schema=SmokeResponse)
    assert settings.target_for(Role.TEACHBACK).provider == "gemini"


@pytest.mark.parametrize("raw", ["", "not json", "[]", '{"message":3}', '{"wrong":"secret"}'])
def test_invalid_response(raw):
    with pytest.raises(InvalidResponseError) as exc:
        validate_json(raw, SmokeResponse)
    assert "secret" not in str(exc.value)


@pytest.mark.parametrize(
    "settings",
    [
        Settings(),
        Settings(live_enabled=True),
        Settings(live_enabled=True, free_tier_confirmed=True),
    ],
)
def test_live_guards(settings):
    with patch("ai.clients.gemini.genai.Client") as sdk:
        with pytest.raises((ConfigurationError, ModelSelectionError)):
            GeminiClient(settings).generate_json(model="x", prompt="test", schema=SmokeResponse)
        sdk.assert_not_called()


@pytest.fixture
def connected():
    settings = Settings(
        gemini_api_key=SecretStr("fake-sensitive-key"),
        live_enabled=True,
        free_tier_confirmed=True,
    )
    with patch("ai.clients.gemini.genai.Client") as factory:
        client = GeminiClient(settings)
        yield client, factory.return_value, factory
        client.close()


def test_gemini_schema_timeout_retry_and_close(connected):
    client, sdk, factory = connected
    sdk.models.generate_content.return_value.text = '{"message":"ready"}'
    assert client.generate_json(
        model="gemini-3.8-flash", prompt="test", schema=SmokeResponse
    ).message
    options = factory.call_args.kwargs["http_options"]
    assert factory.call_args.kwargs["vertexai"] is False
    assert options.base_url == "https://generativelanguage.googleapis.com"
    assert options.timeout == 60000
    assert options.retry_options.attempts == 1
    config = sdk.models.generate_content.call_args.kwargs["config"]
    assert config.response_schema is None
    assert config.response_json_schema == SmokeResponse.model_json_schema()
    assert config.response_json_schema["additionalProperties"] is False
    assert config.max_output_tokens == 4096
    client.close()
    sdk.close.assert_called_once()


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (400, ModelAccessError),
        (401, ModelAccessError),
        (403, ModelAccessError),
        (404, ModelAccessError),
        (429, RateLimitError),
        (500, ProviderError),
    ],
)
def test_safe_api_errors(connected, code, expected):
    client, sdk, _ = connected
    sdk.models.generate_content.side_effect = errors.APIError(
        code, {"message": "fake-sensitive-key"}
    )
    with pytest.raises(expected) as exc:
        client.generate_json(model="x", prompt="test", schema=SmokeResponse)
    assert "fake-sensitive-key" not in str(exc.value)
    assert exc.value.__suppress_context__
    sdk.models.generate_content.assert_called_once()


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (httpx.ReadTimeout("secret"), RequestTimeoutError),
        (httpx.ConnectError("secret"), ProviderError),
    ],
)
def test_network_errors(connected, failure, expected):
    client, sdk, _ = connected
    sdk.models.generate_content.side_effect = failure
    with pytest.raises(expected, match="Gemini"):
        client.generate_json(model="x", prompt="test", schema=SmokeResponse)


def test_access_check(connected):
    client, sdk, _ = connected
    client.check_model_access("gemini-3.8-flash")
    sdk.models.get.assert_called_once_with(model="gemini-3.8-flash")
    sdk.models.generate_content.assert_not_called()


def test_request_budget_prevents_extra_generation(connected):
    client, sdk, _ = connected
    client.request_limit = 1
    sdk.models.generate_content.return_value.text = '{"message":"ready"}'
    client.generate_json(model="x", prompt="test", schema=SmokeResponse)
    with pytest.raises(ConfigurationError, match="budget"):
        client.generate_json(model="x", prompt="test", schema=SmokeResponse)
    assert client.requests_sent == 1
    sdk.models.generate_content.assert_called_once()


def test_truncated_output_is_explicit_error(connected):
    client, sdk, _ = connected
    sdk.models.generate_content.return_value.candidates = [
        MagicMock(finish_reason=MagicMock(value="MAX_TOKENS"))
    ]
    with pytest.raises(InvalidResponseError, match="truncated"):
        client.generate_json(model="x", prompt="test", schema=SmokeResponse)


def test_openai_requires_registered_implementation():
    settings = Settings(
        model_allowlist={
            "openai:future": ModelTarget(provider="openai", model="future", available=True),
            "gemini:fixture-model": ModelTarget(
                provider="gemini", model="fixture-model", available=True
            ),
        },
        routes={Role.EVALUATION: "openai:future"},
        default_model_id="gemini:fixture-model",
    )
    with pytest.raises(ConfigurationError, match="not registered"):
        build_router(settings).generate_json("evaluation", prompt="test", schema=SmokeResponse)


def test_bad_route_and_missing_provider():
    with pytest.raises((ConfigurationError, ModelSelectionError)):
        build_router(Settings()).generate_json("unknown", prompt="test", schema=SmokeResponse)
    with pytest.raises((ConfigurationError, ModelSelectionError)):
        ModelRouter(Settings(), {}).generate_json("teachback", prompt="test", schema=SmokeResponse)


def test_env_precedence_and_secret_redaction(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=local-secret\nGEMINI_MODEL=file-model\n")
    monkeypatch.setenv("GEMINI_MODEL", "env-model")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    settings = Settings.from_env(env_file)
    assert settings.gemini_model == "env-model"
    assert settings.gemini_api_key.get_secret_value() == "local-secret"
    assert "local-secret" not in repr(settings)
    monkeypatch.setenv("AI_MODEL_ROUTES", '{"bad-role":{"provider":"bad","model":"secret"}}')
    with pytest.raises(ConfigurationError) as exc:
        Settings.from_env(env_file)
    assert "secret" not in str(exc.value)
