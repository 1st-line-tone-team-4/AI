"""One explicit question-generation probe. Private diagnostics go to ignored reports only."""

import argparse
import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ai.clients.groq import GroqClient, strict_schema
from ai.config import Settings
from ai.errors import AIError, ConfigurationError
from ai.models import QuestionRequest
from ai.questions import generate, question_batch_schema
from ai.router import ModelRouter


def completion_diagnostics(raw, request, schema, wire_schema):
    """Validate in memory; persist neither generated values nor validator messages."""
    result = {"present": isinstance(raw, str), "raw_saved": False}
    if not isinstance(raw, str):
        return result
    if len(raw) > 100000:
        return {**result, "error_type": "diagnostic_size_limit"}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {
            **result,
            "json_valid": False,
            "error_type": "json_invalid",
            "line": exc.lineno,
            "column": exc.colno,
            "position": exc.pos,
        }

    fields = set()

    def collect(node):
        if isinstance(node, dict):
            fields.update(node.get("properties", {}))
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)

    collect(wire_schema)

    def location(parts):
        return [p if isinstance(p, int) or p in fields else "<field>" for p in parts]

    errors = []
    for error in Draft202012Validator(wire_schema).iter_errors(data):
        errors.append({"loc": location(error.absolute_path), "type": error.validator})
        if len(errors) == 10:
            break
    result.update(json_valid=True, wire_valid=not errors, wire_errors=errors)
    try:
        decoded = schema.model_validate_json(raw, strict=True)
    except ValidationError as exc:
        result.update(
            pydantic_valid=False,
            pydantic_errors=[
                {"loc": location(e["loc"]), "type": e["type"]}
                for e in exc.errors(include_input=False, include_context=False, include_url=False)[
                    :10
                ]
            ],
        )
        return result

    result["pydantic_valid"] = True
    try:
        # Reuse all final question checks, without a provider or a network request.
        generate(request, SimpleNamespace(generate_json=lambda *args, **kwargs: decoded))
    except AIError as exc:
        result.update(question_contract_valid=False, contract_error_type=type(exc).__name__)
    else:
        result["question_contract_valid"] = True
    return result


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--live", action="store_true", required=True)
    args.add_argument("--request", type=Path, default=Path("reports/manual-question-request.json"))
    args.add_argument("--strict", action="store_true")
    args.add_argument("--report", type=Path, default=Path("reports/question-generation-probe.json"))
    options = args.parse_args()
    report = {
        "success": False,
        "generation_budget": 1,
        "automatic_retries": 0,
        "strict_output": options.strict,
        "request_file": str(options.request),
    }
    client = None
    captured = {}
    started = time.perf_counter()
    try:
        settings = Settings.from_env(Path(".env")).model_copy(
            update={"groq_strict_outputs": options.strict}
        )
        request = QuestionRequest.model_validate_json(options.request.read_text(encoding="utf-8"))
        if not request.model_id or not request.model_id.startswith("groq:"):
            raise ConfigurationError(
                "This bounded probe supports the configured Groq request only."
            )
        schema = question_batch_schema(
            request.count, tuple(request.question_types), request.difficulty
        )
        target = settings.target_for("question_generation", request.model_id)
        expected = schema.model_json_schema()
        if options.strict:
            expected = strict_schema(expected)

        def capture_request(outgoing):
            body = json.loads(outgoing.content)
            output = body.get("response_format", {})
            spec = output.get("json_schema", {})
            actual = spec.get("schema", {})
            captured["request_metadata"] = {
                "model": target.model,
                "model_matches": body.get("model") == target.model,
                "max_completion_tokens": body.get("max_completion_tokens"),
                "reasoning_effort": body.get("reasoning_effort", "provider_default"),
                "reasoning_format": body.get("reasoning_format", "provider_default"),
                "response_format": output.get("type"),
                "strict": spec.get("strict"),
                "schema_matches": actual == expected,
                "schema_sha256": hashlib.sha256(
                    json.dumps(actual, sort_keys=True).encode()
                ).hexdigest(),
            }
            # This expected schema depends only on validated count/type/difficulty,
            # never on source text, identifiers, credentials or generated content.
            if actual == expected:
                captured["wire_schema"] = expected

        def capture(response):
            captured["provider_http_status"] = response.status_code
            response.read()
            try:
                data = response.json()
            except ValueError:
                captured["provider_error"] = {"type": "non_json_response"}
                return
            if response.status_code >= 400:
                error = data.get("error", {}) if isinstance(data, dict) else {}
                if isinstance(error, dict):
                    captured["provider_error"] = {
                        "code": (
                            error.get("code")
                            if error.get("code") in {"json_validate_failed", "invalid_json_schema"}
                            else "other"
                        ),
                        "schema_rejected": str(error.get("message", "")).startswith(
                            "invalid JSON schema"
                        ),
                    }
                    captured["failed_generation_diagnostics"] = completion_diagnostics(
                        error.get("failed_generation", data.get("failed_generation")),
                        request,
                        schema,
                        expected,
                    )
            elif isinstance(data, dict) and data.get("choices"):
                content = data["choices"][0].get("message", {}).get("content")
                if isinstance(content, str):
                    captured["completion_diagnostics"] = completion_diagnostics(
                        content, request, schema, expected
                    )

        client = GroqClient(settings, request_limit=1)
        client._client().event_hooks["request"].append(capture_request)
        client._client().event_hooks["response"].append(capture)
        result = generate(request, ModelRouter(settings, {"groq": client}))
        report["success"] = True
        report["actual_count"] = len(result.items)
        report["actual_types"] = [item.question.question_type for item in result.items]
    except (AIError, OSError, ValueError) as exc:
        report["error_type"] = type(exc).__name__
    finally:
        report.update(captured)
        report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        report["requests_sent"] = client.requests_sent if client else 0
        if client:
            report["usage"] = client.usage
            client.close()
        options.report.parent.mkdir(parents=True, exist_ok=True)
        options.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            {
                key: report.get(key)
                for key in (
                    "success",
                    "provider_http_status",
                    "requests_sent",
                    "actual_count",
                    "error_type",
                )
            }
        )
        print(f"Private report: {options.report}")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
