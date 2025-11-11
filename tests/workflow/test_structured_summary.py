from __future__ import annotations

import logging

import pytest

from jupyter_ai.workflow.common.services.final_answer_composer import FinalAnswerComposer
from jupyter_ai.workflow.common.services.structured_summary import (
    SummaryOutline,
    SummaryReference,
    SummarySection,
    SummaryStageService,
    SummaryUnit,
)
from jupyter_ai.workflow.common.worklog.plan_steps import PlanStep


def build_plan_steps():
    return [
        PlanStep(step_id="step-1", title="Collect data", status="completed"),
        PlanStep(step_id="step-2", title="Write summary", status="in_progress"),
    ]


@pytest.mark.asyncio
async def test_summary_stage_includes_citations():
    service = SummaryStageService()
    payload = {
        "overall_summary": "Processed the main tasks.",
        "items": [
            {
                "step_id": "step-1",
                "title": "Collect data",
                "status": "completed",
                "details": "Fetched the latest notebook metrics.",
            }
        ],
        "next_actions": ["Finish the summary draft."],
    }
    section = await service.render(summary_payload=payload, plan_steps=build_plan_steps())

    assert "서머라이즈" in section.text
    assert "Fetched the latest notebook metrics" in section.text
    assert "[계획: Collect data]" in section.text
    assert "[작업: Collect data]" in section.text
    assert "후속 작업" in section.text
    assert section.outline.units[0].step_id == "step-1"


@pytest.mark.asyncio
async def test_summary_stage_fills_from_plan_when_items_missing():
    service = SummaryStageService()
    section = await service.render(summary_payload=None, plan_steps=build_plan_steps())
    assert "계획 단계 'Collect data'" in section.text
    assert "서머라이즈" in section.text


class StubNarrator:
    def __init__(self, text: str):
        self.text = text
        self.calls = 0
        self.enabled = True

    async def narrate(self, outline):
        self.calls += 1
        return self.text


@pytest.mark.asyncio
async def test_summary_stage_uses_narrator_when_available():
    narrator = StubNarrator("서머라이즈\n1. LLM summary [계획: Collect data]")
    service = SummaryStageService(narrator=narrator)
    section = await service.render(summary_payload=None, plan_steps=build_plan_steps())
    assert section.text == narrator.text
    assert narrator.calls == 1


@pytest.mark.asyncio
async def test_final_answer_composer_prefixes_summary_section():
    summary_section = SummarySection(
        outline=SummaryOutline(
            overall_summary="Done.",
            units=(
                SummaryUnit(
                    title="Collect data",
                    details="Fetched samples (상태: completed)",
                    references=(
                        SummaryReference(label="Collect data", ref_id="step-1", stage="plan"),
                    ),
                ),
            ),
            next_actions=(),
        ),
        text="서머라이즈\n1. Collect data\n   - Fetched samples (상태: completed)\n   - 출처: [계획: Collect data]",
    )
    composer = FinalAnswerComposer(
        model_id=None,
        model_args={},
        logger=logging.getLogger("final-answer-test"),
    )
    updates: list[str] = []

    async def _capture(text: str) -> None:
        updates.append(text)

    final_text = await composer.compose(
        summary_payload={},
        fallback_text="최종 결과입니다.",
        summary_section=summary_section,
        on_update=_capture,
    )

    assert final_text.startswith("최종 결과입니다.")
    assert "주요 발견" in final_text
    assert updates[-1] == final_text
    assert all("서머라이즈" not in update for update in updates)
