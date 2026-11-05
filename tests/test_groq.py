import json
from unittest.mock import patch

import httpx
import pytest
from pydantic import SecretStr

from ai.api import create_app
from ai.clients.base import ImageInput
from ai.clients.groq import GroqClient, strict_schema
from ai.config import ModelTarget, Settings
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
from ai.material import OCRText
from ai.models import AnalysisPart, DraftConcept, DraftUnit
from ai.router import build_router, request_router

MODEL = "qwen/qwen3.8-27b"
MODEL_ID = "groq:" + MODEL


def configured(**kwargs):
    return Settings(
        live_enabled=True,
        groq_api_key=SecretStr("fake-groq-secret"),
        model_allowlist={
            MODEL_ID: ModelTarget(
                provider="groq", model=MODEL, available=True, supports_images=True
            )
        },
        **kwargs,
    )


def completion(content, **changes):
    return {
        "choices": [{"finish_reason": "stop", "message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        **changes,
    }


def test_minimal_openai_compatible_payload_and_image_schema(context):
    seen = []

    def handle(request):
        seen.append(request)
        assert request.url.host == "api.groq.com"
        assert request.headers["Authorization"] == "Bearer fake-groq-secret"
        body = json.loads(request.content)
        assert set(body) == {"model", "messages", "max_completion_tokens", "response_format"}
        assert body["model"] == MODEL and body["max_completion_tokens"] == 4096
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["schema"] == OCRText.model_json_schema()
        assert body["response_format"]["json_schema"]["strict"] is False
        assert body["messages"][0]["content"][1]["image_url"]["url"].startswith(
            "data:image/png;base64,"
        )
        return httpx.Response(
            200, json=completion(json.dumps({"text": "한국어 설명", "uncertainty_notes": []}))
        )

    client = GroqClient(configured(), transport=httpx.MockTransport(handle))
    try:
        result = client.generate_json(
            model=MODEL,
            prompt="Read JSON",
            schema=OCRText,
            images=[ImageInput(b"test-pixels", "image/png")],
        )
        assert result.text == "한국어 설명" and client.requests_sent == 1
        assert client.usage == [{"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}]
        assert len(seen) == 1
    finally:
        client.close()


@pytest.mark.parametrize(
    ("code", "error"),
    [
        (429, RateLimitError),
        (502, ProviderBadGatewayError),
        (503, ProviderServiceUnavailableError),
        (504, RequestTimeoutError),
        (401, ModelAccessError),
        (403, ModelAccessError),
        (404, ModelAccessError),
        (400, ProviderRequestError),
        (422, ProviderRequestError),
        (500, ProviderError),
        (302, ProviderError),
    ],
)
def test_http_failures_are_safe_distinct_and_never_retried(code, error):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(
            code, json={"error": {"message": "fake-groq-secret"}}, headers={"retry-after": "5"}
        )

    client = GroqClient(configured(), transport=httpx.MockTransport(handle))
    with pytest.raises(error) as exc:
        client.generate_json(model=MODEL, prompt="test", schema=OCRText)
    assert "fake-groq-secret" not in str(exc.value)
    assert len(calls) == 1 and client.requests_sent == 1
    assert client.rate_limits["retry-after"] == "5"
    client.close()


def test_strict_schema_preserves_property_names_and_domain_schema():
    from pydantic import create_model

    schema = create_model("NamedFields", default=(str, ...), format=(str, ...)).model_json_schema()
    converted = strict_schema(schema)
    assert set(converted["properties"]) == {"default", "format"}
    assert set(converted["required"]) == {"default", "format"}
    assert converted["additionalProperties"] is False
    assert "additionalProperties" not in schema


def test_exact_question_wire_schema_closes_objects_and_pairs_answer_types():
    from ai.models import QuestionBatch
    from ai.questions import question_batch_schema

    schema = strict_schema(
        question_batch_schema(2, ("multiple_choice", "short_answer"), "easy").model_json_schema()
    )
    assert schema["properties"]["items"]["minItems"] == 2
    assert schema["properties"]["items"]["maxItems"] == 2
    for definition in schema["$defs"].values():
        if definition.get("type") == "object":
            assert definition["additionalProperties"] is False
            assert set(definition["required"]) == set(definition["properties"])
    assert "oneOf" not in json.dumps(schema) and "discriminator" not in json.dumps(schema)

    def check_unions(node):
        if isinstance(node, dict):
            for alternative in node.get("anyOf", []):
                assert alternative.get("type") in {"array", "string", "null"}
            for value in node.values():
                check_unions(value)
        elif isinstance(node, list):
            for value in node:
                check_unions(value)

    check_unions(schema)
    assert QuestionBatch.model_json_schema()["properties"]["items"]["minItems"] == 1


def test_strict_output_can_be_explicitly_disabled():
    def handle(request):
        output = json.loads(request.content)["response_format"]["json_schema"]
        assert output["strict"] is False
        assert output["schema"] == OCRText.model_json_schema()
        return httpx.Response(200, json=completion('{"text":"ok","uncertainty_notes":[]}'))

    client = GroqClient(
        configured(groq_strict_outputs=False), transport=httpx.MockTransport(handle)
    )
    try:
        assert client.generate_json(model=MODEL, prompt="test", schema=OCRText).text == "ok"
    finally:
        client.close()


def test_question_generation_strict_wire_roundtrip_preserves_public_contract(context, stored):
    from ai.models import QuestionRequest
    from ai.questions import generate
    from ai.router import ModelRouter

    settings = configured(groq_strict_outputs=True)
    choice = stored.model_dump(mode="json")
    choice["correct_answer"]["text"] = None
    short = stored.model_dump(mode="json")
    short["question"].update(
        question_type="short_answer", options=[], prompt="Name the source use."
    )
    short["correct_answer"] = {
        "type": "short_answer",
        "selected_option_ids": None,
        "text": "habits",
    }

    def handle(request):
        output = json.loads(request.content)["response_format"]["json_schema"]
        assert output["strict"] is True
        assert list(output["schema"]["properties"]) == ["items"]
        assert output["schema"]["properties"]["items"]["minItems"] == 2
        assert output["schema"]["properties"]["items"]["maxItems"] == 2
        return httpx.Response(200, json=completion(json.dumps({"items": [choice, short]})))

    client = GroqClient(settings, transport=httpx.MockTransport(handle))
    try:
        request = QuestionRequest(
            context=context,
            model_id=MODEL_ID,
            unit_id=context.concepts[0].unit_id,
            concept_version_ids=[context.concepts[0].version.id],
            count=2,
            difficulty="easy",
        )
        result = generate(request, ModelRouter(settings, {"groq": client}))
        assert len(result.items) == 2 and client.requests_sent == 1
        assert set(result.items[0].correct_answer.model_dump()) == {"type", "selected_option_ids"}
        assert set(result.items[1].correct_answer.model_dump()) == {"type", "text"}
    finally:
        client.close()


def test_timeout_distinct_from_503():
    def handle(request):
        raise httpx.ReadTimeout("fake-groq-secret", request=request)

    client = GroqClient(configured(), transport=httpx.MockTransport(handle))
    with pytest.raises(RequestTimeoutError) as exc:
        client.generate_json(model=MODEL, prompt="test", schema=OCRText)
    assert "fake-groq-secret" not in str(exc.value)
    client.close()


def test_schema_rejection_exposes_bounded_reason_without_key():
    client = GroqClient(
        configured(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                400,
                json={
                    "error": {
                        "param": "response_format",
                        "message": "invalid JSON schema: anyOf "
                        "keyset_required_overlap fake-groq-secret",
                    }
                },
            )
        ),
    )
    try:
        with pytest.raises(ProviderRequestError, match="keyset_required_overlap") as error:
            client.generate_json(model=MODEL, prompt="test", schema=OCRText)
        assert "fake-groq-secret" not in str(error.value)
        assert client.requests_sent == 1
    finally:
        client.close()


@pytest.mark.parametrize("raw", ["not JSON", '{"text":42,"uncertainty_notes":[]}', "{}"])
def test_existing_pydantic_validation_rejects_bad_json(raw):
    client = GroqClient(
        configured(),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=completion(raw))),
    )
    with pytest.raises(InvalidResponseError):
        client.generate_json(model=MODEL, prompt="test", schema=OCRText)
    assert client.requests_sent == 1
    client.close()


def test_existing_nested_analysis_schema_roundtrip(context):
    concept = DraftConcept(
        name="평서문",
        summary="사실을 나타내는 문장",
        checklist_items=["습관 설명"],
        keywords=["평서문"],
        evidence=context.concepts[0].version.evidence,
    )
    part = AnalysisPart(units=[DraftUnit(title="문장의 종류", concepts=[concept])])
    client = GroqClient(
        configured(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=completion(part.model_dump_json()))
        ),
    )
    assert client.generate_json(model=MODEL, prompt="test", schema=AnalysisPart) == part
    client.close()


def test_model_metadata_check_does_not_generate():
    calls = []

    def handle(request):
        calls.append(request)
        assert request.method == "GET" and request.url.path.endswith("/models")
        return httpx.Response(200, json={"data": [{"id": MODEL, "active": True}]})

    client = GroqClient(configured(), transport=httpx.MockTransport(handle))
    client.check_model_access(MODEL)
    assert client.requests_sent == 0 and len(calls) == 1
    client.close()


def test_generation_budget_and_missing_key_block_network():
    client = GroqClient(
        configured(),
        request_limit=0,
        transport=httpx.MockTransport(lambda request: pytest.fail("No request allowed")),
    )
    with pytest.raises(ConfigurationError, match="budget"):
        client.generate_json(model=MODEL, prompt="test", schema=OCRText)
    assert client.requests_sent == 0
    client.close()
    client = GroqClient(Settings(live_enabled=True))
    with pytest.raises(ConfigurationError, match="GROQ_API_KEY"):
        client.generate_json(model=MODEL, prompt="test", schema=OCRText)
    assert client.requests_sent == 0


def test_request_byok_is_used_and_client_closed():
    with patch("ai.router.GroqClient") as factory:
        with request_router(configured(), MODEL_ID, "request-only-key") as router:
            assert "groq" in router.clients
        assert factory.call_args.args[0].groq_api_key.get_secret_value() == "request-only-key"
        factory.return_value.close.assert_called_once()
    assert "gemini" in build_router(configured()).clients


def test_groq_catalog_does_not_require_new_sdk():
    from fastapi.testclient import TestClient

    settings = configured(server_api_key=SecretStr("server-key"))
    with TestClient(create_app(settings)) as client:
        rows = client.get("/internal/models", headers={"X-AI-API-Key": "server-key"}).json()["data"]
        assert rows == [{"id": MODEL_ID, "provider": "groq", "label": MODEL_ID, "available": True}]


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (ProviderBadGatewayError("HTTP 502"), 502, "PROVIDER_BAD_GATEWAY"),
        (ProviderServiceUnavailableError("HTTP 503"), 503, "PROVIDER_SERVICE_UNAVAILABLE"),
        (RequestTimeoutError("timeout"), 504, "PROVIDER_TIMEOUT"),
        (RateLimitError("quota"), 429, "RATE_LIMITED"),
    ],
)
def test_groq_http_errors_preserve_distinction(context, error, status, code):
    from fastapi.testclient import TestClient

    settings = configured(server_api_key=SecretStr("server-key"))
    with patch("ai.router.GroqClient") as factory:
        factory.return_value.generate_json.side_effect = error
        with TestClient(create_app(settings)) as client:
            response = client.post(
                "/internal/materials/analyze",
                headers={"X-AI-API-Key": "server-key", "X-AI-Key": "test-key"},
                json={"model_id": MODEL_ID, "chunks": [context.chunks[0].model_dump(mode="json")]},
            )
            assert response.status_code == status and response.json()["error"]["code"] == code


def test_live_runner_missing_key_records_no_success_or_calls(tmp_path, monkeypatch):
    from ai import groq_smoke

    report_path = tmp_path / "groq.json"
    monkeypatch.setattr("sys.argv", ["groq_smoke", "--live", "--report", str(report_path)])
    monkeypatch.setattr(groq_smoke.Settings, "from_env", lambda path: Settings())
    with patch.object(groq_smoke, "GroqClient", side_effect=AssertionError("No API call")):
        assert groq_smoke.main() == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "blocked_missing_key" and report["requests_sent"] == 0
    assert report["success"] is False and report["steps"] == []
    assert "concept_analysis" in report["not_run"]


def test_korean_pdf_fixture_is_real_and_has_only_first_page_test_content():
    from pathlib import Path

    import pymupdf

    path = Path(__file__).parent / "fixtures" / "groq_korean.pdf"
    with pymupdf.open(path) as pdf:
        assert pdf.page_count == 2
        assert all(word in pdf[0].get_text() for word in ("평서문", "의문문", "부정문"))
        assert "테스트 요청 대상이 아닙니다" in pdf[1].get_text()


@pytest.mark.parametrize("key", ["bad\nheader", "한글키", "x" * 513])
def test_invalid_key_format_fails_without_exposing_key_or_network(key):
    settings = configured().model_copy(update={"groq_api_key": SecretStr(key)})
    client = GroqClient(settings)
    with patch("ai.clients.groq.httpx.Client", side_effect=AssertionError("No HTTP client")):
        with pytest.raises(ConfigurationError):
            client.generate_json(model=MODEL, prompt="test", schema=OCRText)
    assert client.requests_sent == 0
