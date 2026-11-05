import json
from unittest.mock import patch

import httpx
import pytest
from pydantic import SecretStr

from ai import learning_smoke
from ai.clients.groq import GroqClient
from ai.config import ModelTarget


def test_offline_learning_flow_never_constructs_provider(tmp_path):
    with patch("ai.learning_smoke.GroqClient", side_effect=AssertionError("No provider allowed")):
        report = learning_smoke.run(report_path=tmp_path / "offline.json")
    assert report["status"] == "offline_passed_live_not_run"
    assert report["success"] is False and report["requests_sent"] == 0
    assert report["usage"] == []
    assert all(s["status"] == "passed" for s in report["steps"])
    assert report["steps"][2]["checks"]["cases"] == 25
    assert report["not_run"] == [
        "question_generation",
        "generated_question_grading",
        "teachback_first_question",
        "understanding_evaluation",
    ]


@pytest.mark.parametrize("fail_student", [False, True])
def test_bounded_flow_with_explicit_transport_fixtures(settings, tmp_path, fail_student):
    """Transport fixtures test orchestration, never evidence of live LLM quality."""
    context = learning_smoke.load_context()
    items = [q.model_dump(mode="json") for q in learning_smoke.fixture_questions(context)]
    items[0]["correct_answer"]["text"] = None
    items[1]["correct_answer"]["selected_option_ids"] = None
    concept = context.concepts[0]
    evidence = concept.version.evidence[0].model_dump(mode="json")
    payloads = [
        {"items": items},
        {"question": "다른 상황에도 적용할 수 있는지 설명해 줄래요?"},
        {
            "items": [
                {
                    "checklist_item_id": str(c.id),
                    "status": status,
                    "description": "Test fixture judgment",
                    "confidence": "medium",
                    "evidence": [evidence],
                    "learner_quote": "현재형은 반복되는 습관을 나타냅니다." if i == 0 else "",
                }
                for i, (c, status) in enumerate(
                    zip(concept.version.checklist_items, ["explained", "omission"], strict=True)
                )
            ],
            "next_action": "Review third-person verb endings.",
        },
    ]
    calls = []
    settings = settings.model_copy(
        update={
            "live_enabled": True,
            "groq_api_key": SecretStr("fake-groq-secret"),
            "model_allowlist": {
                "groq:qwen/qwen3.8-27b": ModelTarget(
                    provider="groq",
                    model="qwen/qwen3.8-27b",
                    available=True,
                )
            },
        }
    )

    def handle(request):
        calls.append(request)
        if fail_student and len(calls) == 2:
            return httpx.Response(503, json={"error": {"message": "PRIVATE_SOURCE"}})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(payloads[len(calls) - 1], ensure_ascii=False)
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    def create(config, **kwargs):
        return GroqClient(config, transport=httpx.MockTransport(handle), **kwargs)

    output = tmp_path / "flow.json"
    with (
        patch("ai.learning_smoke.Settings.from_env", return_value=settings),
        patch("ai.learning_smoke.GroqClient", side_effect=create),
    ):
        report = learning_smoke.run(live=True, report_path=output)
    text = output.read_text(encoding="utf-8")
    for private in [
        "fake-groq-secret",
        "PRIVATE_SOURCE",
        context.chunks[0].text,
        payloads[1]["question"],
        str(concept.version.id),
    ]:
        assert private not in text
    assert report["requests_sent"] == len(calls) == (2 if fail_student else 3)
    if fail_student:
        assert report["success"] is False
        assert report["steps"][-1]["name"] == "teachback_first_question"
        assert report["steps"][-1]["status"] == "failed"
        assert report["not_run"] == ["understanding_evaluation"]
    else:
        assert report["success"] and report["context_unchanged"]
        assert all(s["status"] == "passed" for s in report["steps"])
        assert report["steps"][-1]["checks"]["coverage"] == 0.5
        assert report["steps"][-1]["checks"]["statuses"] == {"explained": 1, "omission": 1}
