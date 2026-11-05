from ai.context import make_prompt, payload, select_version
from ai.errors import InputError, InvalidResponseError
from ai.models import Message, StudentQuestion, TeachbackRequest, TeachbackResult
from ai.pdf import normalized
from ai.router import ModelRouter

PROMPT = """You are a student, NEVER the teacher or evaluator. Ask exactly ONE natural,
open-ended clarification question about a missing, vague or inconsistent part of the user's
explanation. Use prior conversation to avoid repetition. Never state the correct answer,
definition, correction or a leading question that embeds the answer. Do not assign a score.
curious_beginner: ask an accessible why/how question about a foundational gap.
confused_friend: describe your confusion briefly and request clarification without giving a hint.
exam_candidate: ask for reasoning or application needed for an exam, without revealing the solution.
Only return question, on one line, ending with exactly one question mark (? or ？).
Example form: 'Could you explain why that step follows?' Do not repeat this example mechanically.
"""


def respond(request: TeachbackRequest, router: ModelRouter | None = None) -> TeachbackResult:
    concept = select_version(request.context, request.concept_version_id)
    history = [*request.history, Message(role="user", content=request.content)]
    if request.final_answer:
        return TeachbackResult(
            history=history, question=None, question_count=3, ready_for_evaluation=True
        )
    if request.question_count >= 3:
        raise InputError(
            "QUESTION_LIMIT_REACHED: use the final-answer operation without an AI call."
        )
    if router is None:
        raise InputError("Student question generation requires a selected model and X-AI-Key.")
    result = router.generate_json(
        "teachback",
        model_id=request.model_id,
        prompt=make_prompt(
            PROMPT,
            {
                **payload(request.context, [concept]),
                "history": [m.model_dump() for m in history],
                "explanation_language": request.explanation_language,
                "student_persona": request.student_persona,
            },
        ),
        schema=StudentQuestion,
    )
    question = result.question.strip()
    if (
        not question.endswith(("?", "？"))
        or len(question.splitlines()) != 1
        or question.count("?") + question.count("？") != 1
    ):
        raise InvalidResponseError("Student must ask exactly one clarification question.")
    summary = normalized(concept.version.summary or "")
    if summary and summary in normalized(question):
        raise InvalidResponseError("Student question exposes the source definition.")
    history.append(Message(role="assistant", content=question))
    return TeachbackResult(
        history=history,
        question=question,
        question_count=request.question_count + 1,
        ready_for_evaluation=False,
    )
