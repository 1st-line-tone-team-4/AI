"""Bounded learning integration probe; reports contain checks, never source or response text."""

import argparse
import json
from collections import Counter
from itertools import product
from pathlib import Path

from ai import evaluation, questions, teachback
from ai.clients.groq import GroqClient
from ai.config import Settings
from ai.context import allowed_chunks, select_version, validate_sources
from ai.errors import AIError, InputError, ModelRequiredError, RateLimitError
from ai.models import (
    CriterionJudgment,
    EvaluationJudgments,
    EvaluationRequest,
    GradeRequest,
    MultipleChoiceAnswer,
    Option,
    PublicQuestionDraft,
    QuestionRequest,
    ShortAnswer,
    StoredQuestion,
    StudyContext,
    TeachbackRequest,
)
from ai.pdf import extract_pdf, normalized
from ai.router import ModelRouter

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
STATES = {"explained": 1, "partial": 0.5, "omission": 0, "error": 0, "unverified": 0}


def check(condition):
    if not condition:
        raise InputError("Learning integration check failed; no response text was logged.")


def load_context():
    context = StudyContext.model_validate_json(
        (FIXTURE / "backend_context.json").read_text(encoding="utf-8")
    )
    check(len(context.concepts) == 1)
    concept = select_version(context, context.concepts[0].version.id)
    document = extract_pdf((FIXTURE / "english_grammar.pdf").read_bytes())
    pages = {p.number: p.text for p in document.pages}
    for chunk in context.chunks:
        check(normalized(chunk.text) == normalized(pages[chunk.page_number]))
    validate_sources(concept.version.evidence, context.chunks)
    return context


def fixture_questions(context):
    """Known grading inputs only; never presented as generated LLM output."""
    concept = context.concepts[0]
    common = dict(
        concept_ids=[concept.concept_id],
        concept_version_ids=[concept.version.id],
        evidence=concept.version.evidence,
        difficulty="easy",
    )
    choice = StoredQuestion(
        question=PublicQuestionDraft(
            **common,
            question_type="multiple_choice",
            prompt="What does the simple present describe?",
            options=[Option(id="A", text="Habits"), Option(id="B", text="Only past events")],
        ),
        correct_answer=MultipleChoiceAnswer(type="multiple_choice", selected_option_ids=["A"]),
        explanation="The source states that the simple present describes habits.",
    )
    short = StoredQuestion(
        question=PublicQuestionDraft(
            **common, question_type="short_answer", options=[], prompt="Name the repeated actions."
        ),
        correct_answer=ShortAnswer(type="short_answer", text="habits"),
        explanation="Repeated actions are habits.",
    )
    return [choice, short]


def grade_checks(context, items):
    choice = next(q for q in items if q.question.question_type == "multiple_choice")
    short = next(q for q in items if q.question.question_type == "short_answer")
    wrong_id = next(
        o.id
        for o in choice.question.options
        if o.id not in choice.correct_answer.selected_option_ids
    )
    cases = [
        ("choice_correct", choice, choice.correct_answer, True),
        (
            "choice_incorrect",
            choice,
            MultipleChoiceAnswer(type="multiple_choice", selected_option_ids=[wrong_id]),
            False,
        ),
        ("short_exact", short, short.correct_answer, True),
        (
            "short_normalized",
            short,
            ShortAnswer(type="short_answer", text=f"  {short.correct_answer.text.upper()}  "),
            True,
        ),
    ]
    for _, stored, answer, expected in cases:
        result = questions.grade(
            GradeRequest(context=context, stored_question=stored, answer=answer)
        )
        check(result.is_correct is expected)
        check(result.correct_answer == stored.correct_answer)
        check(result.explanation == stored.explanation)
        check(result.evidence == stored.question.evidence)
        questions.validate_question(stored.question, context)
    return {name: True for name, *_ in cases}


def weighted_checks(context):
    concept = context.concepts[0]
    check(len(concept.version.checklist_items) == 2)
    for states in product(STATES, repeat=2):
        judgments = EvaluationJudgments(
            items=[
                CriterionJudgment(
                    checklist_item_id=c.id,
                    status=status,
                    description="Explicit score-calculation test input, not an AI judgment.",
                    confidence="medium",
                    evidence=concept.version.evidence,
                    learner_quote="",
                )
                for c, status in zip(concept.version.checklist_items, states, strict=True)
            ],
            next_action="Review the checklist.",
        )
        result = evaluation.calculate_report(judgments, concept)
        count = sum(s != "unverified" for s in states)
        score = sum(STATES[s] for s in states)
        check(result.coverage == (round(score / count, 4) if count else None))
        check(result.assessable_count == count and result.weighted_score == score)
        check(result.concept_version_id == concept.version.id)
        check(
            {i.checklist_item_id for i in result.items}
            == {c.id for c in concept.version.checklist_items}
        )
        check(all(i.concept_id == concept.concept_id for i in result.items))
    return {"cases": 25, "states": list(STATES), "formula": "weighted-v1"}


def run(*, live=False, report_path=Path("reports/learning-integration.json")):
    report = {"success": False, "steps": [], "requests_sent": 0, "usage": [], "live": live}
    client = None

    def step(name, kind, function):
        row = {"name": name, "verification": kind, "status": "running"}
        report["steps"].append(row)
        before = client.requests_sent if client else 0
        usage_start = len(client.usage) if client else 0
        try:
            output = function()
            row.update(status="passed", checks=output)
        finally:
            row["requests_sent"] = (client.requests_sent if client else 0) - before
            row["usage"] = client.usage[usage_start:] if client else []

    try:
        context = load_context()
        snapshot = context.model_dump_json()
        concept = context.concepts[0]
        step(
            "source_and_confirmed_version",
            "local_python",
            lambda: {
                "pdf_source_matches": True,
                "confirmed": True,
                "concepts": 1,
                "identifier_origin": "preassigned_fixture_UUIDs_not_backend_DB",
            },
        )
        step(
            "fixture_grading",
            "local_python",
            lambda: grade_checks(context, fixture_questions(context)),
        )
        step("weighted_v1_all_states", "local_python", lambda: weighted_checks(context))
        # This fallback must request a model, rather than invent a local semantic verdict.
        short = fixture_questions(context)[1]
        try:
            questions.grade(
                GradeRequest(
                    context=context,
                    stored_question=short,
                    answer=ShortAnswer(type="short_answer", text="A different expression"),
                )
            )
        except ModelRequiredError:
            step("semantic_grading_boundary", "local_python", lambda: {"requires_model": True})
        else:
            check(False)
        if not live:
            report["status"] = "offline_passed_live_not_run"
            return report

        settings = Settings.from_env(Path(".env")).model_copy(update={"groq_strict_outputs": True})
        model_id = "groq:" + settings.groq_model
        client = GroqClient(settings, request_limit=3)
        report["model"] = settings.target_for("question_generation", model_id).model

        def capture(response):
            row = report["steps"][-1]
            row["provider_http_status"] = response.status_code
            if response.status_code >= 400:
                response.read()
                try:
                    error = response.json().get("error", {})
                except (ValueError, AttributeError):
                    error = {}
                code = error.get("code") if isinstance(error, dict) else None
                row["provider_error_code"] = (
                    code if code in {"json_validate_failed", "invalid_json_schema"} else "other"
                )

        client._client().event_hooks["response"].append(capture)
        router = ModelRouter(settings, {"groq": client})

        def quota():
            for key in ("x-ratelimit-remaining-requests", "x-ratelimit-remaining-tokens"):
                value = client.rate_limits.get(key)
                if value is not None and value.isdigit() and int(value) == 0:
                    raise RateLimitError("Quota exhausted; next learning request not sent.")

        def generation():
            nonlocal generated
            generated = questions.generate(
                QuestionRequest(
                    model_id=model_id,
                    context=context,
                    unit_id=concept.unit_id,
                    concept_version_ids=[concept.version.id],
                    count=2,
                    difficulty="easy",
                    question_types=["multiple_choice", "short_answer"],
                    explanation_language="ko",
                ),
                router,
            )
            return {
                "count": len(generated.items),
                "types": [q.question.question_type for q in generated.items],
            }

        generated = None
        step("question_generation", "live_groq", generation)
        step(
            "generated_question_grading",
            "local_python",
            lambda: grade_checks(context, generated.items),
        )
        quota()

        def student():
            nonlocal dialogue
            dialogue = teachback.respond(
                TeachbackRequest(
                    model_id=model_id,
                    context=context,
                    concept_version_id=concept.version.id,
                    explanation_language="ko",
                    student_persona="curious_beginner",
                    content=(
                        "현재형은 반복되는 습관을 나타냅니다. "
                        "I study English every day가 예시입니다."
                    ),
                    question_count=0,
                ),
                router,
            )
            check(dialogue.question_count == 1 and len(dialogue.history) == 2)
            return {"questions": 1, "history_roles": [m.role for m in dialogue.history]}

        dialogue = None
        step("teachback_first_question", "live_groq", student)
        quota()

        def assess():
            result = evaluation.evaluate(
                EvaluationRequest(
                    model_id=model_id,
                    context=context,
                    concept_version_id=concept.version.id,
                    explanation_language="ko",
                    history=dialogue.history,
                ),
                router,
            )
            check(result.concept_version_id == concept.version.id)
            check(
                {i.checklist_item_id for i in result.items}
                == {c.id for c in concept.version.checklist_items}
            )
            check(
                all(
                    i.concept_version_id == concept.version.id
                    and i.concept_id == concept.concept_id
                    for i in result.items
                )
            )
            for item in result.items:
                validate_sources(item.evidence, allowed_chunks(context, [concept]))
            count = sum(i.status != "unverified" for i in result.items)
            score = sum(STATES[i.status] for i in result.items)
            check(result.coverage == (round(score / count, 4) if count else None))
            check(result.assessable_count == count and result.weighted_score == score)
            return {
                "statuses": dict(Counter(i.status for i in result.items)),
                "coverage": result.coverage,
                "weighted_score": result.weighted_score,
                "assessable_count": count,
                "evidence_and_version_ids_consistent": True,
            }

        step("understanding_evaluation", "live_groq", assess)
        check(context.model_dump_json() == snapshot)
        report.update(success=True, status="live_passed", context_unchanged=True)
    except (AIError, OSError, ValueError, StopIteration) as exc:
        if report["steps"] and report["steps"][-1]["status"] == "running":
            report["steps"][-1].update(status="failed", error_type=type(exc).__name__)
        report.update(status="failed", error_type=type(exc).__name__)
    finally:
        if client:
            report.update(requests_sent=client.requests_sent, usage=client.usage)
            client.close()
        if not report["success"]:
            attempted = {s["name"] for s in report["steps"]}
            report["not_run"] = [
                name
                for name in (
                    "question_generation",
                    "generated_question_grading",
                    "teachback_first_question",
                    "understanding_evaluation",
                )
                if name not in attempted
            ]
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("reports/learning-integration.json"))
    args = parser.parse_args()
    report = run(live=args.live, report_path=args.report)
    print({key: report[key] for key in ("status", "success", "requests_sent", "usage")})
    return 0 if report["status"] in {"offline_passed_live_not_run", "live_passed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
