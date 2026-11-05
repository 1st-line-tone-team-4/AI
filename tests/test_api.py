from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from ai.api import create_app
from ai.config import Settings
from ai.errors import (
    ConfigurationError,
    InvalidResponseError,
    ModelAccessError,
    ProviderError,
    RateLimitError,
    RequestTimeoutError,
)
from ai.models import MultipleChoiceAnswer, StudentQuestion, TeachbackRequest
from ai.router import ModelRouter

HEADERS = {"X-AI-API-Key": "local-test-server-key"}
MODEL_ID = "gemini:fixture-model"


@pytest.fixture
def client(settings, parse_payload):
    settings = settings.model_copy(update={"server_api_key": SecretStr(HEADERS["X-AI-API-Key"])})
    import pymupdf

    def recognize(data, mime):
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            return parse_payload(len(pdf))

    with patch("ai.document_parse.UpstageDocumentParser._request", side_effect=recognize):
        with TestClient(create_app(settings)) as client:
            yield client


def teachback_payload(context):
    return TeachbackRequest(
        context=context,
        concept_version_id=context.concepts[0].version.id,
        model_id=MODEL_ID,
        explanation_language="ko",
        student_persona="curious_beginner",
        content="The simple present describes habits.",
        question_count=0,
    ).model_dump(mode="json")


def test_health_docs_internal_only_and_no_backend_duplication(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert all(path == "/health" or path.startswith("/internal/") for path in schema["paths"])
    assert "/study-plan" not in schema["paths"] and "/questions/recommend" not in schema["paths"]
    assert schema["components"]["securitySchemes"]["ProviderBYOK"]["name"] == "X-AI-Key"
    assert "/internal/explanations/generate" not in schema["paths"]
    assert "/internal/teachback/respond" in schema["paths"]
    assert (
        client.post("/internal/explanations/generate", headers=HEADERS, json={}).status_code == 404
    )


@pytest.mark.parametrize("headers", [{}, {"X-AI-API-Key": "wrong"}])
def test_all_function_routes_require_server_auth(client, headers):
    schema = client.get("/openapi.json").json()
    for path in schema["paths"]:
        if path != "/health":
            method = client.get if path == "/internal/models" else client.post
            assert method(path, headers=headers).status_code == 401


def test_no_server_key_fails_closed():
    with pytest.raises(ConfigurationError):
        with TestClient(create_app(Settings())):
            raise AssertionError("Startup must fail")


def test_mocked_parse_and_real_txt_http(client, pdf_data):
    result = client.post(
        "/internal/materials/extract",
        content=pdf_data,
        headers={**HEADERS, "Content-Type": "application/pdf"},
    )
    assert result.status_code == 200 and len(result.json()["document"]["pages"]) == 2
    assert "id" not in result.json()["chunk_drafts"][0]
    result = client.post(
        "/internal/materials/extract",
        content=b"Simple present describes habits.",
        headers={**HEADERS, "Content-Type": "text/plain"},
    )
    assert result.status_code == 200 and result.json()["document"]["pages"][0]["number"] == 1


def test_pdf_errors_and_size_bound(client):
    headers = {**HEADERS, "Content-Type": "application/pdf"}
    assert (
        client.post("/internal/materials/extract", content=b"bad", headers=headers).status_code
        == 422
    )
    assert (
        client.post(
            "/internal/materials/extract", content=b"x" * (20 * 1024 * 1024 + 1), headers=headers
        ).status_code
        == 413
    )
    assert (
        client.post(
            "/internal/teachback/respond", content=b"x" * (2 * 1024 * 1024 + 1), headers=HEADERS
        ).status_code
        == 413
    )


def test_validation_does_not_echo_private_inputs(client):
    result = client.post(
        "/internal/teachback/respond",
        headers=HEADERS,
        json={"concept_version_id": "private-secret-invalid-uuid"},
    )
    assert result.status_code == 422 and "private-secret" not in result.text


def test_unknown_model_rejected_before_provider(client, context):
    body = teachback_payload(context)
    body["model_id"] = "https://attacker.invalid/arbitrary"
    with patch("ai.router.GeminiClient", side_effect=AssertionError("No provider call")):
        result = client.post("/internal/teachback/respond", headers=HEADERS, json=body)
    assert result.status_code == 422 and result.json()["error"]["code"] == "MODEL_NOT_ALLOWED"


def test_http_provider_key_never_falls_back_to_server_key(client, context):
    result = client.post(
        "/internal/teachback/respond", headers=HEADERS, json=teachback_payload(context)
    )
    assert result.status_code == 422
    with patch("ai.router.GeminiClient") as factory:
        key = "request-only-private-key"
        factory.return_value.generate_json.side_effect = InvalidResponseError(
            "Rejected fixture output"
        )
        result = client.post(
            "/internal/teachback/respond",
            headers={**HEADERS, "X-AI-Key": key},
            json=teachback_payload(context),
        )
        assert factory.call_args.args[0].gemini_api_key.get_secret_value() == key
        factory.return_value.close.assert_called_once()
        assert key not in result.text


def test_deterministic_grading_needs_no_provider_key(client, context, stored):
    with patch("ai.router.GeminiClient", side_effect=AssertionError("No provider call")):
        result = client.post(
            "/internal/questions/grade",
            headers=HEADERS,
            json={
                "context": context.model_dump(mode="json"),
                "stored_question": stored.model_dump(mode="json"),
                "answer": MultipleChoiceAnswer(
                    type="multiple_choice", selected_option_ids=["A"]
                ).model_dump(),
            },
        )
    assert result.status_code == 200 and result.json()["is_correct"]


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (RateLimitError("quota"), 429, "RATE_LIMITED"),
        (RequestTimeoutError("timeout"), 504, "PROVIDER_TIMEOUT"),
        (InvalidResponseError("schema"), 502, "INVALID_OUTPUT"),
        (ProviderError("upstream"), 502, "PROVIDER_UNAVAILABLE"),
        (ModelAccessError("auth"), 422, "PROVIDER_AUTH"),
    ],
)
def test_provider_errors_map_to_http(client, context, error, status, code):
    with patch("ai.router.GeminiClient") as factory:
        factory.return_value.generate_json.side_effect = error
        result = client.post(
            "/internal/teachback/respond",
            headers={**HEADERS, "X-AI-Key": "test-key"},
            json=teachback_payload(context),
        )
    assert result.status_code == status and result.json()["error"]["code"] == code


def test_teachback_endpoint_actual_postprocessing(client, settings, context):
    result = StudentQuestion(question="Can you give another example?")
    transport = MagicMock()
    transport.generate_json.return_value = result
    router = ModelRouter(settings, {"gemini": transport})

    @contextmanager
    def bound(settings, model_id, key):
        yield router

    with patch("ai.api.request_router", bound):
        response = client.post(
            "/internal/teachback/respond",
            headers={**HEADERS, "X-AI-Key": "test-key"},
            json=teachback_payload(context),
        )
    assert response.status_code == 200
    assert response.json()["question"] == result.question
    assert response.json()["question_count"] == 1


def test_validate_key_never_generates_and_reports_unavailable(client):
    with patch("ai.router.GeminiClient") as factory:
        factory.return_value.check_model_access.side_effect = ProviderError("Unavailable")
        result = client.post(
            "/internal/models/validate-key",
            headers={**HEADERS, "X-AI-Key": "test-key"},
            json={"model_id": MODEL_ID},
        )
        assert result.status_code == 503
        assert result.json()["error"]["code"] == "KEY_VALIDATION_UNAVAILABLE"
        factory.return_value.generate_json.assert_not_called()


def test_parse_requires_no_llm_provider_key(client, pdf_data):
    with patch("ai.router.GeminiClient") as provider:
        result = client.post(
            "/internal/materials/extract",
            content=pdf_data,
            headers={**HEADERS, "Content-Type": "application/pdf"},
        )
    assert result.status_code == 200
    assert result.json()["method"] == "upstage_document_parse"
    provider.assert_not_called()


def test_legacy_selected_page_option_is_not_silently_ignored(client, pdf_data):
    result = client.post(
        "/internal/materials/extract",
        params={"ocr_pages": [1]},
        content=pdf_data,
        headers={**HEADERS, "Content-Type": "application/pdf"},
    )
    assert result.status_code == 422


def test_webp_not_in_backend_contract(client):
    result = client.post(
        "/internal/materials/extract",
        content=b"RIFFinvalidWEBP",
        headers={**HEADERS, "Content-Type": "image/webp"},
    )
    assert result.status_code == 422


def test_extract_docs_do_not_request_llm_model_or_byok(client):
    operation = client.get("/openapi.json").json()["paths"]["/internal/materials/extract"]["post"]
    names = [p["name"] for p in operation.get("parameters", [])]
    assert "model_id" not in names and "max_ocr_pages" not in names
    assert all("ProviderBYOK" not in security for security in operation.get("security", []))
