from datetime import date, datetime, timedelta, timezone
from math import ceil

from pydantic import Field

from src.errors import InputError
from src.models import (
    ConceptTime,
    Model,
    StudyContext,
    StudyTimeEstimate,
    StudyTimeRequest,
    TimeConcept,
)


class WorkloadRequest(Model):
    total_pages: int = Field(ge=1, le=100000)
    context: StudyContext
    exam_date: date
    today: date = Field(default_factory=lambda: datetime.now(timezone(timedelta(hours=9))).date())
    progress: list[TimeConcept] | None = None


class WorkloadEstimate(Model):
    remaining_days: int
    total_pages: int
    concept_count: int
    recommended_daily_pages: int
    recommended_daily_concepts: int
    time_estimate: StudyTimeEstimate
    assumptions: list[str]


def estimate_workload(request: WorkloadRequest) -> WorkloadEstimate:
    from src.context import validate_context

    validate_context(request.context)
    days = max(0, (request.exam_date - request.today).days)
    count = len(request.context.concepts)
    return WorkloadEstimate(
        remaining_days=days,
        total_pages=request.total_pages,
        concept_count=count,
        recommended_daily_pages=ceil(request.total_pages / max(1, days)),
        recommended_daily_concepts=ceil(count / max(1, days)),
        time_estimate=estimate_context_workload(
            request.context,
            exam_date=request.exam_date,
            today=request.today,
            progress=request.progress,
        ),
        assumptions=[
            "단순 학습량 추정이며 날짜별 계획·일정·DB 레코드를 생성하지 않습니다.",
            "시험 전 남은 일수로 나누며 당일·시험 경과는 1일로 계산합니다.",
            "복습일 배정·코스 압축 비율·너무 먼 시험일 기준은 팀 협의 사항입니다.",
        ],
    )


def estimate_study_time(request: StudyTimeRequest) -> StudyTimeEstimate:
    """Independent estimate; does not create tasks, plans, DB records or learner diagnoses."""
    ids = [c.concept_version_id for c in request.concepts]
    if len(ids) != len(set(ids)):
        raise InputError("Duplicate concept versions in time estimate.")
    remaining = max(0, (request.exam_date - request.today).days)
    results = []
    for c in request.concepts:
        factor = {"easy": 0.75, "medium": 1.0, "hard": 1.5}[c.difficulty]
        learning = ceil(c.remaining_criteria * 6 * factor * (1 + c.weakness * 0.5))
        solving = ceil(c.remaining_questions * 3 * factor)
        teachback = ceil(c.teachback_sessions * 5 * factor)
        review_criteria = c.remaining_criteria if c.review_criteria is None else c.review_criteria
        review = ceil(review_criteria * c.review_cycles * 2 * factor * (1 + c.weakness * 0.5))
        results.append(
            ConceptTime(
                concept_version_id=c.concept_version_id,
                name=c.name,
                learning_minutes=learning,
                question_minutes=solving,
                review_minutes=review,
                teachback_minutes=teachback,
                total_minutes=learning + solving + review + teachback,
                priority=round(
                    c.weakness * 2 + (1 if c.remaining_criteria else 0) + c.importance - 0.5, 2
                ),
            )
        )
    results.sort(key=lambda item: -item.priority)
    total = sum(c.total_minutes for c in results)
    daily = ceil(total / max(1, remaining))
    guidance = (
        "Prioritize weak and unlearned concepts, then essential problems; reduce scope with "
        "the learner if the estimated daily workload is impractical."
    )
    if request.exam_date < request.today:
        guidance = "Exam date has passed; this is a remaining-work estimate for today. " + guidance
    elif daily > 180:
        guidance = (
            "Workload exceeds 180 minutes/day; prioritize rather than promise completion. "
            + guidance
        )
    return StudyTimeEstimate(
        remaining_days=remaining,
        total_minutes=total,
        recommended_daily_minutes=daily,
        concepts=results,
        assumptions=[
            "Heuristic estimate, not observed learning speed or a completion guarantee.",
            "6 minutes per remaining criterion, 3 per problem, 2 per criterion per review cycle.",
            "Criterion/review time multiplied by 1 + 0.5 * supplied weakness (0-1).",
            "Difficulty: easy 0.75, medium 1, hard 1.5; 5 minutes per teach-back session.",
            "Importance (0-1) affects priority, not minutes; estimates are not a diagnosis.",
            "Divide by days before exam; today/past uses one day. No time input or diagnosis.",
        ],
        priority_guidance=guidance,
    )


def estimate_context_workload(
    context: StudyContext,
    *,
    exam_date: date,
    today: date,
    progress: list[TimeConcept] | None = None,
) -> StudyTimeEstimate:
    """Use confirmed extracted concepts; backend may supply actual remaining work."""
    by_id = {c.version.id: c for c in context.concepts}
    if progress is not None:
        if set(by_id) != {p.concept_version_id for p in progress}:
            raise InputError("Progress must cover exactly the confirmed versions in context.")
        if any(
            p.remaining_criteria > len(by_id[p.concept_version_id].version.checklist_items)
            for p in progress
        ):
            raise InputError("Remaining criteria exceed the confirmed checklist.")
    else:
        progress = [
            TimeConcept(
                concept_version_id=c.version.id,
                name=c.version.name,
                remaining_criteria=len(c.version.checklist_items),
                remaining_questions=2,
                teachback_sessions=1,
                review_cycles=1,
            )
            for c in context.concepts
        ]
    result = estimate_study_time(
        StudyTimeRequest(exam_date=exam_date, today=today, concepts=progress)
    )
    result.assumptions.append(
        "Without progress: all confirmed criteria unlearned, 2 questions, 1 teach-back, 1 review "
        "per concept; medium difficulty and neutral importance unless backend overrides."
    )
    return result
