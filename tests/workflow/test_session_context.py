import logging

from jupyter_ai.workflow.common.services.session_context import (
    SessionContextLifecycle,
    SessionContextSnapshot,
    SessionContextStore,
    SessionKnowledgeContextBuilder,
)


def test_store_propagates_summary_to_all_targets():
    primary: dict[str, object] = {}
    mirror: dict[str, object] = {}
    store = SessionContextStore(primary, mirrors=(mirror,))

    store.record_summary(summary_text="요약", payload={"overall_summary": "요약"})

    assert primary["final_summary_text"] == "요약"
    assert mirror["final_summary_text"] == "요약"
    assert primary["work_summary"]["overall_summary"] == "요약"


def test_followups_replace_and_clear():
    state: dict[str, object] = {}
    store = SessionContextStore(state)

    store.followups.replace(["A", "B"])
    assert tuple(store.followups.pending()) == ("A", "B")

    store.followups.resolve(["a"])
    assert tuple(store.followups.pending()) == ("B",)

    cleared = store.followups.clear()
    assert cleared is True
    assert store.followups.pending() == ()


def test_lifecycle_records_simple_response_without_plan():
    params: dict[str, object] = {}
    store = SessionContextStore(params)
    lifecycle = SessionContextLifecycle(store, logger=logging.getLogger("test"))

    lifecycle.record_simple_response(
        {
            "content": "Answer body.\nSecond sentence.",
            "needs_plan": False,
        }
    )

    snapshot: SessionContextSnapshot = store.snapshot()
    assert snapshot.summary_text is not None
    assert snapshot.final_answer_text == "Answer body.\nSecond sentence."
    assert snapshot.follow_up_questions == ()


def test_session_knowledge_builder_uses_summary_and_work_items():
    params: dict[str, object] = {
        "final_summary_text": "Notebook run already produced the metrics.",
        "_work_evidence": {
            "items": [
                {"title": "metrics.py", "details": "Generated accuracy=98%"},
                {"title": "notebook", "details": "Saved plots to output.png"},
            ]
        },
    }
    store = SessionContextStore(params)
    builder = SessionKnowledgeContextBuilder(store)

    context = builder.build()

    assert context is not None
    assert "세션 요약" in context.message
    assert "metrics.py" in context.message
    assert context.match.summary == "Notebook run already produced the metrics."
