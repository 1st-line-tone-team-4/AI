"""Explicit Groq development check: one Korean reply, one page OCR, one analysis call."""

import argparse
import json
import re
from pathlib import Path
from uuid import UUID

import pymupdf
from pydantic import Field

from ai.clients.base import ImageInput
from ai.clients.groq import GroqClient
from ai.config import Role, Settings
from ai.errors import AIError, ConfigurationError, InvalidResponseError, RateLimitError
from ai.material import Extraction, OCRText, analyze
from ai.models import AnalyzeRequest, Document, Model, Page, SourceChunk
from ai.router import ModelRouter


class KoreanConnection(Model):
    message: str = Field(min_length=1, max_length=200)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--pdf", type=Path, default=Path("tests/fixtures/groq_korean.pdf"))
    parser.add_argument("--report", type=Path, default=Path("reports/groq-development.json"))
    args = parser.parse_args()
    stages = ["model_access", "korean_connection", "first_page_ocr", "concept_analysis"]
    report = {
        "success": False,
        "status": "not_run",
        "steps": [],
        "requests_sent": 0,
        "generation_budget": 3,
        "schema_mode": "json_schema/best-effort + Pydantic strict",
        "scope": "development test; not a production model decision",
    }
    client = None

    def step(name, input_data, function):
        record = {"name": name, "input": input_data, "success": False}
        report["steps"].append(record)
        try:
            output = function()
            record["output"] = (
                output.model_dump(mode="json") if isinstance(output, Model) else output
            )
            record["success"] = True
            print(f"OK: {name}", flush=True)
            return output
        except (AIError, ValueError, OSError) as exc:
            record["error"] = type(exc).__name__
            raise

    def budget_available():
        for header in ("x-ratelimit-remaining-requests", "x-ratelimit-remaining-tokens"):
            value = client.rate_limits.get(header)
            if value is not None and value.isdigit() and int(value) == 0:
                raise RateLimitError(
                    "Groq response reports exhausted quota; next request not sent."
                )

    try:
        settings = Settings.from_env(Path(".env"))
        report["model"] = settings.groq_model
        if not settings.groq_api_key.get_secret_value().strip():
            report["status"] = "blocked_missing_key"
            raise ConfigurationError("GROQ_API_KEY is missing. No external request was sent.")
        model_id = "groq:" + settings.groq_model
        report["model_id"] = model_id
        settings.target_for(Role.MATERIAL_ANALYSIS, model_id)
        client = GroqClient(settings, request_limit=3)
        router = ModelRouter(settings, {"groq": client})
        step(
            "model_access",
            {"model_id": model_id},
            lambda: client.check_model_access(settings.groq_model),
        )

        def korean_reply():
            output = client.generate_json(
                model=settings.groq_model,
                prompt="한국어로 연결 테스트 확인 문장 하나를 "
                "message에 넣은 JSON 객체를 반환하세요.",
                schema=KoreanConnection,
            )
            if not re.search(r"[가-힣]", output.message):
                raise InvalidResponseError("Connection reply contains no Korean text.")
            return output

        step("korean_connection", {"language": "ko", "schema": "KoreanConnection"}, korean_reply)
        budget_available()
        data = args.pdf.read_bytes()
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            if pdf.page_count < 1:
                raise ConfigurationError("Test PDF has no first page.")
            png = pdf[0].get_pixmap(matrix=pymupdf.Matrix(2, 2)).tobytes("png")
            report["pdf_page_count"] = pdf.page_count

        def first_page():
            output = client.generate_json(
                model=settings.groq_model,
                prompt="Transcribe Korean/English faithfully; return text and uncertainty_notes.",
                schema=OCRText,
                images=[ImageInput(png, "image/png")],
            )
            result = Extraction(
                document=Document(pages=[Page(number=1, text=output.text)]),
                chunk_drafts=[],
                method="explicit_groq_vision_probe",
                warnings=output.uncertainty_notes,
                mime_type="image/png",
            )
            text = result.document.pages[0].text
            if not re.search(r"[가-힣]", text):
                raise InvalidResponseError("OCR output contains no Korean text.")
            if args.pdf.name == "groq_korean.pdf" and not all(
                word in text for word in ("평서문", "의문문", "부정문")
            ):
                raise InvalidResponseError("OCR missed Korean headings in the fictional fixture.")
            return result

        extraction = step("first_page_ocr", {"pdf": str(args.pdf), "pages_sent": [1]}, first_page)
        budget_available()
        # Preassigned fictional fixture IDs only; the AI does not allocate actual backend IDs.
        chunk = SourceChunk(
            id=UUID("10000001-1111-4111-8111-111111111111"),
            material_id=UUID("10000002-1111-4111-8111-111111111111"),
            material_name=args.pdf.name,
            page_number=1,
            text=extraction.document.pages[0].text,
        )
        request = AnalyzeRequest(
            chunks=[chunk],
            explanation_language="ko",
            model_id=model_id,
            max_calls=1,
            chunk_chars=12000,
        )

        def concepts():
            result = analyze(request, router)
            if not any(
                re.search(r"[가-힣]", c.name + c.summary)
                for unit in result.units
                for c in unit.concepts
            ):
                raise InvalidResponseError("Concept output contains no Korean names or summaries.")
            return result

        step("concept_analysis", request.model_dump(mode="json"), concepts)
        report["success"] = True
        report["status"] = "passed"
        return 0
    except (AIError, ValueError, OSError) as exc:
        if report["status"] == "not_run":
            report["status"] = "failed"
        report["error"] = type(exc).__name__
        report["message"] = str(exc)
        print(f"Stopped: {type(exc).__name__}: {exc}", flush=True)
        return 1
    finally:
        if client is not None:
            report["requests_sent"] = client.requests_sent
            report["usage"] = client.usage
            report["rate_limits"] = client.rate_limits
            client.close()
        report["not_run"] = [
            name for name in stages if name not in {record["name"] for record in report["steps"]}
        ]
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Report: {args.report}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
