import json
from unittest.mock import patch

import httpx
import pytest
from pydantic import SecretStr

from ai import question_smoke
from ai.clients.groq import GroqClient, strict_schema
from ai.config import ModelTarget
from ai.models import QuestionRequest
from ai.questions import question_batch_schema


def test_probe_captures_provider_error_once_without_logging_key_or_response(
    settings, context, tmp_path, capsys
):
    model_id = "groq:qwen/qwen3.8-27b"
    settings = settings.model_copy(
        update={
            "live_enabled": True,
            "groq_api_key": SecretStr("fake-groq-secret"),
            "model_allowlist": {
                model_id: ModelTarget(provider="groq", model="qwen/qwen3.8-27b", available=True)
            },
        }
    )
    request = QuestionRequest(
        context=context,
        model_id=model_id,
        unit_id=context.concepts[0].unit_id,
        concept_version_ids=[context.concepts[0].version.id],
        count=2,
        difficulty="easy",
    )
    request_path, report_path = tmp_path / "request.json", tmp_path / "report.json"
    request_path.write_text(request.model_dump_json(), encoding="utf-8")
    seen = []

    def handle(request):
        seen.append(1)
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": "invalid_json_schema",
                    "message": "unsupported minItems fake-groq-secret",
                    "param": "response_format",
                }
            },
        )

    def create(config, **kwargs):
        return GroqClient(config, transport=httpx.MockTransport(handle), **kwargs)

    with (
        patch(
            "sys.argv",
            [
                "probe",
                "--live",
                "--strict",
                "--request",
                str(request_path),
                "--report",
                str(report_path),
            ],
        ),
        patch("ai.question_smoke.Settings.from_env", return_value=settings),
        patch("ai.question_smoke.GroqClient", side_effect=create),
    ):
        assert question_smoke.main() == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert len(seen) == report["requests_sent"] == 1
    assert report["provider_http_status"] == 400
    assert report["provider_error"]["code"] == "invalid_json_schema"
    assert "message" not in report["provider_error"]
    assert "fake-groq-secret" not in report_path.read_text(encoding="utf-8")
    assert "unsupported minItems" not in capsys.readouterr().out


@pytest.mark.parametrize("status", [200, 400])
def test_probe_diagnoses_failed_json_without_saving_private_values(
    settings, context, tmp_path, capsys, status
):
    model_id = "groq:qwen/qwen3.8-27b"
    settings = settings.model_copy(
        update={
            "live_enabled": True,
            "groq_api_key": SecretStr("fake-groq-secret"),
            "model_allowlist": {
                model_id: ModelTarget(provider="groq", model="qwen/qwen3.8-27b", available=True)
            },
        }
    )
    request = QuestionRequest(
        context=context,
        model_id=model_id,
        unit_id=context.concepts[0].unit_id,
        concept_version_ids=[context.concepts[0].version.id],
        count=2,
        difficulty="easy",
    )
    request_path, report_path = tmp_path / "request.json", tmp_path / "report.json"
    request_path.write_text(request.model_dump_json(), encoding="utf-8")
    raw = '{"items":[],"PRIVATE_SOURCE_AND_KEY_fake-groq-secret":"PRIVATE_CONTENT"}'
    calls = []

    def handle(outgoing):
        calls.append(outgoing)
        if status == 400:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": "json_validate_failed",
                        "message": "PRIVATE_CONTENT fake-groq-secret",
                        "failed_generation": raw,
                    }
                },
            )
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": raw}}]}
        )

    def create(config, **kwargs):
        return GroqClient(config, transport=httpx.MockTransport(handle), **kwargs)

    with (
        patch(
            "sys.argv",
            [
                "probe",
                "--live",
                "--strict",
                "--request",
                str(request_path),
                "--report",
                str(report_path),
            ],
        ),
        patch("ai.question_smoke.Settings.from_env", return_value=settings),
        patch("ai.question_smoke.GroqClient", side_effect=create),
    ):
        assert question_smoke.main() == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    key = "failed_generation_diagnostics" if status == 400 else "completion_diagnostics"
    diagnostic = report[key]
    assert diagnostic["present"] and diagnostic["json_valid"]
    assert not diagnostic["raw_saved"] and not diagnostic["wire_valid"]
    assert {e["type"] for e in diagnostic["wire_errors"]} == {"minItems", "additionalProperties"}
    assert diagnostic["pydantic_valid"] is False
    assert report["request_metadata"]["strict"] is True
    assert report["request_metadata"]["schema_matches"] is True
    assert report["wire_schema"]["properties"]["items"]["minItems"] == 2
    assert report["requests_sent"] == len(calls) == 1
    persisted = report_path.read_text(encoding="utf-8") + capsys.readouterr().out
    for private in [
        "fake-groq-secret",
        "PRIVATE_SOURCE",
        "PRIVATE_CONTENT",
        context.chunks[0].text,
    ]:
        assert private not in persisted
    assert "failed_completion" not in report and "output" not in report


def test_failure_diagnostics_cover_syntax_contract_and_valid_mixed_output(context, stored):
    request = QuestionRequest(
        context=context,
        unit_id=context.concepts[0].unit_id,
        concept_version_ids=[context.concepts[0].version.id],
        count=2,
        difficulty="easy",
    )
    schema = question_batch_schema(2, tuple(request.question_types), "easy")
    wire = strict_schema(schema.model_json_schema())
    invalid = question_smoke.completion_diagnostics('{"items": [PRIVATE', request, schema, wire)
    assert invalid["json_valid"] is False and invalid["position"] > 0
    assert "PRIVATE" not in json.dumps(invalid)
    assert question_smoke.completion_diagnostics(None, request, schema, wire)["present"] is False
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
    data = {"items": [choice, short]}
    result = question_smoke.completion_diagnostics(json.dumps(data), request, schema, wire)
    assert result["wire_valid"] and result["pydantic_valid"] and result["question_contract_valid"]
    # A wire-valid answer can still violate the original public/domain contract.
    choice["correct_answer"]["selected_option_ids"] = ["PRIVATE_UNKNOWN_OPTION"]
    result = question_smoke.completion_diagnostics(json.dumps(data), request, schema, wire)
    assert result["wire_valid"] and result["pydantic_valid"]
    assert result["question_contract_valid"] is False
    assert "PRIVATE_UNKNOWN_OPTION" not in json.dumps(result)
