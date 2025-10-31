import asyncio

from jupyter_ai.worklog import (
    WorklogController,
    WorklogRepository,
    build_worklog_entry,
    build_worklog_patch,
)


def test_final_answer_publisher_receives_trimmed_value():
    repository = WorklogRepository()
    controller = WorklogController(repository)

    published_patches: list[str | None] = []
    final_answers: list[tuple[str, str]] = []

    async def patch_publisher(patch):
        published_patches.append(getattr(patch, "final_answer", None))

    async def final_publisher(entry_id: str, final_answer: str):
        final_answers.append((entry_id, final_answer))

    controller.set_publisher(patch_publisher)
    controller.set_final_answer_publisher(final_publisher)

    repository.upsert(build_worklog_entry("entry-1"))
    asyncio.run(
        controller.update_entry(
            build_worklog_patch("entry-1", final_answer="  Result ready  ")
        )
    )

    assert published_patches == ["  Result ready  "]
    assert final_answers == [("entry-1", "Result ready")]


def test_final_answer_publisher_ignored_for_blank_value():
    repository = WorklogRepository()
    controller = WorklogController(repository)

    final_answers: list[tuple[str, str]] = []

    def final_publisher(entry_id: str, final_answer: str) -> None:
        final_answers.append((entry_id, final_answer))

    controller.set_final_answer_publisher(final_publisher)

    repository.upsert(build_worklog_entry("entry-2"))
    asyncio.run(
        controller.update_entry(
            build_worklog_patch("entry-2", final_answer="   ")
        )
    )

    assert final_answers == []


def test_emit_command_event_invokes_publisher():
    repository = WorklogRepository()
    controller = WorklogController(repository)

    events: list[tuple[str, dict[str, object]]] = []

    def publisher(entry_id: str, payload: dict[str, object]) -> None:
        events.append((entry_id, payload))

    controller.set_command_publisher(publisher)
    asyncio.run(controller.emit_command_event("entry-3", {"command_id": "cmd"}))

    assert events == [("entry-3", {"command_id": "cmd"})]
