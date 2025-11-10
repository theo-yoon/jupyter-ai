from __future__ import annotations

import asyncio

import pytest

from jupyter_ai.workflow.common.services.reasoning_summary import ReasoningSummaryService


@pytest.mark.asyncio
async def test_reasoning_summary_service_fallback():
    service = ReasoningSummaryService(shared={}, model_id=None, model_args=None)
    summary = await service.summarize(reasoning_text="analyze dataset and prepare plots")
    assert summary.title == "Analyze dataset and prepare plots"
    assert summary.details == "analyze dataset and prepare plots"
    assert summary.actions == []
    metadata = summary.to_metadata()
    assert metadata["summary_title"] == summary.title
    assert metadata["summary_generated"] is False


@pytest.mark.asyncio
async def test_reasoning_summary_service_limits_title_words():
    service = ReasoningSummaryService(shared={}, model_id=None, model_args=None)
    text = "Investigate the failing integration tests thoroughly before release"
    summary = await service.summarize(reasoning_text=text)
    assert summary.title == "Investigate the failing integration tests thoroughly before release"
