from ai.context import allowed_chunks, make_prompt, payload, select_version, validate_sources
from ai.errors import InputError, InvalidResponseError
from ai.models import (
    ConfirmedConcept,
    EvaluationJudgments,
    EvaluationRequest,
    EvaluationResult,
    PersistedReportItem,
    ReportItem,
    SessionReport,
)
from ai.pdf import normalized
from ai.router import ModelRouter

PROMPT = """You are an evaluator, separate from the AI student. Assess only learner/user messages.
Never treat the student's questions as learner knowledge. Evaluate every fixed checklist criterion
exactly once using its supplied checklist_item_id. Do not create or renumber criterion IDs.
explained: learner states the essential meaning correctly, including necessary conditions.
partial: relevant understanding is present but an essential condition or detail is incomplete.
omission: learner has not addressed the criterion; do not confuse omission with a factual error.
error: explicit source-contradicting learner claim; cite learner_quote AND source evidence.
unverified: source, transcription or learner wording cannot establish a reliable judgment.
Each assessable result needs source evidence. explained/partial/error need an exact contiguous
quote from one user message. omission can have learner_quote=''. Never infer error from silence.
Return confidence low/medium/high, a concrete description, and an actionable overall next_action.
Do not produce coverage, weighted_score or any numeric grade; Python computes weighted-v1.
"""


def calculate_report(judgments: EvaluationJudgments, concept: ConfirmedConcept) -> EvaluationResult:
    expected = {i.id for i in concept.version.checklist_items}
    ids = [i.checklist_item_id for i in judgments.items]
    if set(ids) != expected or len(ids) != len(expected):
        raise InvalidResponseError(
            "Every fixed checklist criterion must have exactly one judgment."
        )
    weights = {"explained": 1, "partial": 0.5, "omission": 0, "error": 0}
    assessable = sum(i.status != "unverified" for i in judgments.items)
    score = sum(weights.get(i.status, 0) for i in judgments.items)
    weak = [
        i.checklist_item_id for i in judgments.items if i.status in ("partial", "omission", "error")
    ]
    by_id = {i.checklist_item_id: i for i in judgments.items}
    items = [
        ReportItem(
            concept_id=concept.concept_id,
            concept_version_id=concept.version.id,
            **by_id[c.id].model_dump(exclude={"learner_quote"}),
        )
        for c in concept.version.checklist_items
    ]
    return EvaluationResult(
        concept_version_id=concept.version.id,
        coverage=round(score / assessable, 4) if assessable else None,
        assessable_count=assessable,
        weighted_score=score,
        items=items,
        next_action=judgments.next_action,
        weak_checklist_item_ids=weak,
        weak_concept_ids=[concept.concept_id] if weak else [],
    )


def evaluate(request: EvaluationRequest, router: ModelRouter) -> EvaluationResult:
    concept = select_version(request.context, request.concept_version_id)
    learners = [m.content for m in request.history if m.role == "user"]
    if not learners:
        raise InputError("Report requires at least one learner message.")
    result = router.generate_json(
        "evaluation",
        model_id=request.model_id,
        prompt=make_prompt(
            PROMPT,
            {
                **payload(request.context, [concept]),
                "learner_messages": learners,
                "explanation_language": request.explanation_language,
            },
        ),
        schema=EvaluationJudgments,
    )
    for item in result.items:
        validate_sources(item.evidence, allowed_chunks(request.context, [concept]), generated=True)
        quote = normalized(item.learner_quote)
        if quote and not any(quote in normalized(message) for message in learners):
            raise InvalidResponseError("Evaluation fabricated a learner quote.")
        if item.status != "unverified" and (
            not item.evidence or (item.status in ("explained", "partial", "error") and not quote)
        ):
            item.status = "unverified"
            item.confidence = "low"
            item.description = "Insufficient evidence to assess this criterion. " + item.description
    return calculate_report(result, concept)


def session_report(
    result: EvaluationResult, *, report_id, session_id, version_no: int, action_id, item_ids: dict
) -> SessionReport:
    """Build the public DTO only after the backend supplies every persistence ID."""
    expected = {i.checklist_item_id for i in result.items}
    if set(item_ids) != expected or len(set(item_ids.values())) != len(item_ids):
        raise InputError("Backend must supply one distinct report-item ID per criterion.")
    return SessionReport(
        id=report_id,
        session_id=session_id,
        version_no=version_no,
        action_id=action_id,
        concept_version_id=result.concept_version_id,
        coverage=result.coverage,
        coverage_formula=result.coverage_formula,
        assessable_count=result.assessable_count,
        weighted_score=result.weighted_score,
        next_action=result.next_action,
        items=[
            PersistedReportItem(id=item_ids[i.checklist_item_id], **i.model_dump())
            for i in result.items
        ],
    )
