"""Explicit live workflow; never run by pytest or when the server starts."""

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pymupdf
from pydantic import BaseModel

from ai import evaluation, material, questions, tagging, teachback
from ai.clients.base import ImageInput
from ai.clients.gemini import GeminiClient
from ai.config import Role, Settings
from ai.errors import AIError, ConfigurationError
from ai.models import (
    AnalyzeRequest,
    EvaluationRequest,
    GradeRequest,
    QuestionRequest,
    ShortAnswer,
    StudyContext,
    StudyTimeRequest,
    TagRequest,
    TeachbackRequest,
    TimeConcept,
)
from ai.pdf import extract_pdf
from ai.router import ModelRouter
from ai.study_time import estimate_study_time


def main():
    parser = argparse.ArgumentParser(
        description="Explicit provider workflow on a supplied snapshot."
    )
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--confirm-free-tier", action="store_true", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--max-calls", type=int, default=8, choices=range(1, 9))
    parser.add_argument(
        "--snapshot", type=Path, default=Path("tests/fixtures/backend_context.json")
    )
    parser.add_argument("--pdf", type=Path, default=Path("tests/fixtures/english_grammar.pdf"))
    parser.add_argument("--with-image", action="store_true")
    parser.add_argument("--check-access-only", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("reports/live.json"))
    args = parser.parse_args()
    report = {
        "success": False,
        "steps": [],
        "requests_sent": 0,
        "integration": "standalone",
        "snapshot_note": "Supplied IDs only; test snapshot is not a live backend connection.",
    }
    client = None

    def step(name, request, function):
        data = request.model_dump(mode="json") if isinstance(request, BaseModel) else request
        record = {"name": name, "input": data, "success": False}
        report["steps"].append(record)
        try:
            result = function()
            record["output"] = (
                result.model_dump(mode="json") if isinstance(result, BaseModel) else result
            )
            record["success"] = True
            print(f"OK: {name}", flush=True)
            return result
        except (AIError, ValueError, OSError) as exc:
            record["error"] = type(exc).__name__
            raise

    try:
        settings = Settings.from_env(Path(".env"))
        if not settings.free_tier_confirmed:
            raise ConfigurationError(
                "Confirm the free development project's quota before live testing."
            )
        target = settings.target_for(Role.MATERIAL_ANALYSIS, args.model_id)
        if target.provider != "gemini":
            raise ConfigurationError(
                "This live runner uses the currently configured Gemini credential."
            )
        client = GeminiClient(settings, request_limit=args.max_calls)
        router = ModelRouter(settings, {"gemini": client})
        step(
            "model_access",
            {"model_id": args.model_id},
            lambda: client.check_model_access(target.model),
        )
        if args.check_access_only:
            report["success"] = True
            return 0
        if settings.max_output_tokens < 2048:
            raise ConfigurationError("Use at least 2048 output tokens for full feature outputs.")
        context = StudyContext.model_validate_json(args.snapshot.read_text(encoding="utf-8"))
        extraction = step(
            "pdf_extract",
            {"path": str(args.pdf)},
            lambda: extract_pdf(args.pdf.read_bytes()),
        )
        pages = {p.number: p.text for p in extraction.pages}
        if any(c.text.strip() not in pages.get(c.page_number, "") for c in context.chunks):
            raise ConfigurationError("Snapshot chunks do not match the supplied PDF.")
        concept = context.concepts[0]
        if args.with_image:
            with pymupdf.open(stream=args.pdf.read_bytes(), filetype="pdf") as pdf:
                png = pdf[0].get_pixmap().tobytes("png")
            step(
                "image_ocr",
                {"source": "rendered first PDF page"},
                lambda: router.generate_json(
                    "material_ocr",
                    model_id=args.model_id,
                    prompt="Transcribe image text faithfully; return text and uncertainty_notes.",
                    schema=material.OCRText,
                    images=[ImageInput(png, "image/png")],
                ),
            )
        request = AnalyzeRequest(
            chunks=context.chunks, model_id=args.model_id, explanation_language="en", max_calls=1
        )
        step("draft_analysis", request, lambda: material.analyze(request, router))
        request = QuestionRequest(
            context=context,
            unit_id=concept.unit_id,
            concept_version_ids=[concept.version.id],
            count=2,
            difficulty="easy",
            model_id=args.model_id,
            explanation_language="en",
        )
        batch = step("question_generation", request, lambda: questions.generate(request, router))
        mc = next(q for q in batch.items if q.question.question_type == "multiple_choice")
        request = GradeRequest(
            context=context, stored_question=mc, answer=mc.correct_answer, model_id=args.model_id
        )
        step("python_grading", request, lambda: questions.grade(request))
        short = next(q for q in batch.items if q.question.question_type == "short_answer")
        request = GradeRequest(
            context=context,
            stored_question=short,
            model_id=args.model_id,
            answer=ShortAnswer(type="short_answer", text="A regular habitual action."),
        )
        step("semantic_grading", request, lambda: questions.grade(request, router))
        request = TeachbackRequest(
            context=context,
            concept_version_id=concept.version.id,
            model_id=args.model_id,
            explanation_language="en",
            student_persona="curious_beginner",
            question_count=0,
            content="The simple present describes habits.",
        )
        conversation = step("teachback", request, lambda: teachback.respond(request, router))
        request = EvaluationRequest(
            context=context,
            concept_version_id=concept.version.id,
            history=conversation.history,
            model_id=args.model_id,
            explanation_language="en",
        )
        step("weighted_report", request, lambda: evaluation.evaluate(request, router))
        request = TagRequest(context=context, question=mc.question, model_id=args.model_id)
        step("keywords", request, lambda: tagging.suggest(request, router))
        today = datetime.now(timezone(timedelta(hours=9))).date()
        request = StudyTimeRequest(
            exam_date=today + timedelta(days=7),
            today=today,
            concepts=[
                TimeConcept(
                    concept_version_id=concept.version.id,
                    name=concept.version.name,
                    remaining_criteria=len(concept.version.checklist_items),
                    remaining_questions=2,
                )
            ],
        )
        step("study_time_estimate", request, lambda: estimate_study_time(request))
        report["success"] = True
        return 0
    except (AIError, ValueError, OSError) as exc:
        report["error"] = type(exc).__name__
        report["message"] = str(exc)
        print(f"Stopped: {type(exc).__name__}: {exc}", flush=True)
        return 1
    finally:
        if client is not None:
            report["requests_sent"] = client.requests_sent
            report["usage"] = client.usage
            client.close()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Report: {args.report}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
