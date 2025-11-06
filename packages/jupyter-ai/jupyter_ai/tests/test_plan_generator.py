import json
from types import SimpleNamespace

import pytest

from jupyter_ai.workflow.common.knowledge import KnowledgeContext, KnowledgeMatch
from jupyter_ai.workflow.common.planning import generate_plan_steps, summarize_user_query


class _DummyMessage(SimpleNamespace):
    pass


class _DummyChoice(SimpleNamespace):
    pass


class _DummyResponse(SimpleNamespace):
    pass


@pytest.mark.anyio
async def test_generate_plan_steps_from_llm(monkeypatch):
    content = """
    ```json
{
  "steps": [
    {"title": "기존 WorkNodeList 구성 및 요구사항 검토"},
    {"title": "확장 가능한 WorkNodeList UI 리팩터링"},
    {"title": "요약/최종 답변 섹션 추가 및 카드 레이아웃 정리"},
    {"title": "관련 타입/스토어 업데이트 및 회귀 검증"}
  ]
}
    ```
    """
    response = _DummyResponse(
        choices=[
            _DummyChoice(
                message=_DummyMessage(content=content)
            )
        ]
    )

    async def _fake_completion(*args, **kwargs):
        return response

    monkeypatch.setattr(
        "jupyter_ai.workflow.common.planning.dynamic.acompletion",
        _fake_completion,
    )

    steps = await generate_plan_steps(
        "새 기능을 구현해줘",
        model_id="dummy",
        model_args={},
    )

    titles = [step.title for step in steps]
    assert titles == [
        "기존 WorkNodeList 구성 및 요구사항 검토",
        "확장 가능한 WorkNodeList UI 리팩터링",
        "요약/최종 답변 섹션 추가 및 카드 레이아웃 정리",
        "관련 타입/스토어 업데이트 및 회귀 검증",
    ]


@pytest.mark.anyio
async def test_generate_plan_steps_from_tool_call(monkeypatch):
    plan_payload = {
        "steps": [
            {"title": "Inspect project directory"},
            {"title": "Create analysis notebook"},
            {"title": "Draft pandas example"},
        ]
    }
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {
            "name": "submit_plan",
            "arguments": json.dumps(plan_payload),
        },
    }
    response = _DummyResponse(
        choices=[
            _DummyChoice(
                message=_DummyMessage(
                    tool_calls=[tool_call],
                    content=None,
                )
            )
        ]
    )

    async def _fake_completion(*args, **kwargs):
        return response

    monkeypatch.setattr(
        "jupyter_ai.workflow.common.planning.dynamic.acompletion",
        _fake_completion,
    )

    steps = await generate_plan_steps(
        "내 디렉토리 파일 확인해보고 새로운 노트북 생성해주고 간단한 판다스 예제코드 작성해봐",
        model_id="dummy",
        model_args={},
    )

    titles = [step.title for step in steps]
    assert titles == [
        "Inspect project directory",
        "Create analysis notebook",
        "Draft pandas example",
    ]


@pytest.mark.anyio
async def test_generate_plan_steps_falls_back_on_error(monkeypatch):
    async def _raising_completion(*args, **kwargs):
        raise RuntimeError("LLM failure")

    monkeypatch.setattr(
        "jupyter_ai.workflow.common.planning.dynamic.acompletion",
        _raising_completion,
    )

    steps = await generate_plan_steps(
        "로그 에러를 해결할 수 있도록 도와줘",
        model_id="dummy",
        model_args={},
    )

    assert len(steps) == 1
    step = steps[0]
    assert step.metadata and step.metadata.get("origin") == "fallback"
    assert step.title.startswith("Handle request:")


@pytest.mark.anyio
async def test_generate_plan_steps_without_model_uses_fallback():
    steps = await generate_plan_steps(
        "간단한 작업을 도와줘",
        model_id=None,
        model_args={},
    )

    assert len(steps) == 1
    step = steps[0]
    assert step.metadata and step.metadata.get("origin") == "fallback"
    assert "Handle request:" in step.title or step.title.startswith("Review the request")


@pytest.mark.anyio
async def test_generate_plan_steps_handles_malformed_json(monkeypatch):
    content = """
    {
      "steps": [
        {"title": "Inspect inventory dataset"},
        {"title": "Implement sales trend analysis"},
        {"title": "Summarize insights for stakeholders"},
    """
    response = _DummyResponse(
        choices=[_DummyChoice(message=_DummyMessage(content=content))]
    )

    async def _fake_completion(*args, **kwargs):
        return response

    monkeypatch.setattr(
        "jupyter_ai.workflow.common.planning.dynamic.acompletion",
        _fake_completion,
    )

    steps = await generate_plan_steps(
        "재고 데이터를 분석해서 판매 추세를 보여줘.",
        model_id="dummy",
        model_args={},
    )

    titles = [step.title for step in steps]
    assert titles == [
        "Inspect inventory dataset",
        "Implement sales trend analysis",
        "Summarize insights for stakeholders",
    ]


@pytest.mark.anyio
async def test_generate_plan_steps_handles_single_quoted_payload(monkeypatch):
    content = """{'steps': [
        {'title': 'Inspect project directory'},
        {'title': 'Create analysis notebook'},
        {'title': 'Draft pandas example'}
    ]}"""
    response = _DummyResponse(
        choices=[_DummyChoice(message=_DummyMessage(content=content))]
    )

    async def _fake_completion(*args, **kwargs):
        return response

    monkeypatch.setattr(
        "jupyter_ai.workflow.common.planning.dynamic.acompletion",
        _fake_completion,
    )

    steps = await generate_plan_steps(
        "내 디렉토리 파일 확인해보고 새로운 노트북 생성해주고 간단한 판다스 예제코드 작성해봐",
        model_id="dummy",
        model_args={},
    )

    titles = [step.title for step in steps]
    assert titles == [
        "Inspect project directory",
        "Create analysis notebook",
        "Draft pandas example",
    ]


@pytest.mark.anyio
async def test_generate_plan_steps_preserves_existing_tool_choice(monkeypatch):
    response = _DummyResponse(
        choices=[
            _DummyChoice(
                message=_DummyMessage(
                    content=json.dumps(
                        {
                            "steps": [
                                {"title": "Inspect project directory"},
                                {"title": "Create analysis notebook"},
                            ]
                        }
                    )
                )
            )
        ]
    )

    captured = {}

    async def _fake_completion(*args, **kwargs):
        captured["tool_choice"] = kwargs.get("tool_choice")
        return response

    monkeypatch.setattr(
        "jupyter_ai.workflow.common.planning.dynamic.acompletion",
        _fake_completion,
    )

    steps = await generate_plan_steps(
        "데이터 확인하고 노트북 만들어줘",
        model_id="dummy",
        model_args={"tool_choice": "auto"},
    )

    assert captured.get("tool_choice") == "auto"
    titles = [step.title for step in steps]
    assert titles == [
        "Inspect project directory",
        "Create analysis notebook",
    ]


@pytest.mark.anyio
async def test_generate_plan_steps_retries_without_enforced_tool(monkeypatch):
    responses = [
        _DummyResponse(
            choices=[_DummyChoice(message=_DummyMessage(content=""))]
        ),
        _DummyResponse(
            choices=[
                _DummyChoice(
                    message=_DummyMessage(
                        content=json.dumps(
                            {
                                "steps": [
                                    {"title": "Inspect dataset"},
                                    {"title": "Analyze cohorts"},
                                    {"title": "Summarize findings"},
                                ]
                            }
                        )
                    )
                )
            ]
        ),
    ]

    call_args = []

    async def _fake_completion(*args, **kwargs):
        call_args.append(kwargs.get("tool_choice"))
        return responses[len(call_args) - 1]

    monkeypatch.setattr(
        "jupyter_ai.workflow.common.planning.dynamic.acompletion",
        _fake_completion,
    )

    steps = await generate_plan_steps(
        "마케팅 데이터셋 분석 계획을 세워줘",
        model_id="dummy",
        model_args={},
    )

    assert len(call_args) == 2
    assert isinstance(call_args[0], dict)
    assert call_args[1] is None

    titles = [step.title for step in steps]
    assert titles == [
        "Inspect dataset",
        "Analyze cohorts",
        "Summarize findings",
    ]


@pytest.mark.anyio
async def test_summarize_user_query_from_llm(monkeypatch):
    content = """
    {
      "summary": "Analyze loyalty events and Holiday Promo performance"
    }
    """
    response = _DummyResponse(
        choices=[_DummyChoice(message=_DummyMessage(content=content))]
    )

    async def _fake_completion(*args, **kwargs):
        return response

    monkeypatch.setattr(
        "jupyter_ai.workflow.common.planning.dynamic.acompletion",
        _fake_completion,
    )

    summary = await summarize_user_query(
        "Please look into loyalty events and Holiday Promo performance data.",
        model_id="dummy",
        model_args={},
    )

    assert summary == "Analyze loyalty events and Holiday Promo performance"


@pytest.mark.anyio
async def test_summarize_user_query_handles_single_quoted_payload(monkeypatch):
    content = "{'summary': 'Inspect project files before planning'}"
    response = _DummyResponse(
        choices=[_DummyChoice(message=_DummyMessage(content=content))]
    )

    async def _fake_completion(*args, **kwargs):
        return response

    monkeypatch.setattr(
        "jupyter_ai.workflow.common.planning.dynamic.acompletion",
        _fake_completion,
    )

    summary = await summarize_user_query(
        "내 디렉토리 파일 확인해봐.",
        model_id="dummy",
        model_args={},
    )

    assert summary == "Inspect project files before planning"


@pytest.mark.anyio
async def test_summarize_user_query_fallback_on_failure(monkeypatch):
    async def _raises(*args, **kwargs):
        raise RuntimeError("fail")

    monkeypatch.setattr(
        "jupyter_ai.workflow.common.planning.dynamic.acompletion",
        _raises,
    )

    summary = await summarize_user_query(
        "다음주까지 신규 사용자 유입 데이터를 정리해줘.",
        model_id="dummy",
        model_args={},
    )

    assert summary is None


@pytest.mark.anyio
async def test_generate_plan_steps_prefers_knowledge_actions(monkeypatch):
    context = KnowledgeContext(
        message="Follow these steps to resolve the issue.",
        follow_up_questions=("추가 로그를 확보하세요.",),
        match=KnowledgeMatch(
            entry_id="voc-kernel-status",
            title="커널 상태 확인 및 정리 가이드",
            summary="커널을 점검하고 정리하는 절차입니다.",
            actions=(
                "Running 패널을 열어 현재 실행 중인 커널을 검토합니다.",
                "장시간 실행된 커널을 종료하고 사용자에게 정리 결과를 확인합니다.",
            ),
            metadata={"owner": "infra-team"},
            tags=("kernel",),
            verifications=("커널 상태 확인",),
            required_context=("사용자 ID",),
            confidence=0.9,
            source="voc",
        ),
    )

    async def _unexpected_completion(*args, **kwargs):
        raise AssertionError("LLM should not be invoked when knowledge actions are available.")

    monkeypatch.setattr(
        "jupyter_ai.workflow.common.planning.dynamic.acompletion",
        _unexpected_completion,
    )

    steps = await generate_plan_steps(
        "커널 상태를 확인하고 정리해줘.",
        model_id="dummy-model",
        model_args={},
        knowledge_context=context,
    )

    titles = [step.title for step in steps]
    assert titles == [
        "Running 패널을 열어 현재 실행 중인 커널을 검토합니다.",
        "장시간 실행된 커널을 종료하고 사용자에게 정리 결과를 확인합니다.",
    ]
    for step in steps:
        assert step.metadata.get("origin") == "knowledge"
        assert step.metadata.get("knowledge_entry_id") == "voc-kernel-status"
