import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jupyter_server.serverapp import ServerApp

from .extended_toolkit import PLAN_AWARE_TOOLKIT
from .tool_output_format import RICH_OUTPUT_KIND, RICH_OUTPUT_VERSION
from .notebook_toolkit import (
    NOTEBOOK_TOOLKIT,
    NotebookToolkitError,
    create_notebook,
    delete_notebook_cell,
    delete_all_notebook_cells,
    _build_notebook_open_payload,
    get_notebook_cell_source,
    insert_notebook_cell,
    list_notebook_cells,
    ensure_notebook_open_command,
    update_notebook_cell,
    run_notebook_all_cells,
    run_notebook_all_above,
    run_notebook_all_below,
    run_notebook_cell,
    run_notebook_cell_and_select_next,
    run_notebook_cell_and_insert_below,
)


class FakeYText:
    def __init__(self, text: str = ""):
        self.text = text

    def to_string(self) -> str:
        return self.text

    def delete(self, index: int, length: int) -> None:
        self.text = self.text[:index] + self.text[index + length :]

    def insert(self, index: int, value: str) -> None:
        self.text = self.text[:index] + value + self.text[index:]


class FakeNotebook:
    def __init__(self, cells):
        self.ycells = cells

    def insert_cell(
        self,
        index,
        cell_type=None,
        source="",
        metadata=None,
        id=None,
        **kwargs,
    ):
        if isinstance(cell_type, dict):
            cell = cell_type
        else:
            cell = {
                "id": id or f"cell-{len(self.ycells)+1}",
                "cell_type": cell_type or "code",
                "source": FakeYText(source),
                "metadata": metadata or {},
            }
        if index < 0:
            index = max(len(self.ycells) + index, 0)
        if index > len(self.ycells):
            index = len(self.ycells)
        self.ycells.insert(index, cell)
        return cell

    def delete_cell(self, index):
        return self.ycells.pop(index)


class FakeCollaboration:
    def __init__(self, mapping):
        self._mapping = mapping

    async def get_document(self, path, content_type=None, file_format=None, copy=True):
        return self._mapping.get(path)


def _source_to_string(value):
    if hasattr(value, "to_string"):
        return value.to_string()
    return value


class FakeContentsManager:
    def __init__(self, root_dir: Path):
        self.root_dir = Path(root_dir)

    async def save(self, model, path):
        abs_path = self.root_dir / Path(path)
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        content = model.get("content")
        if model.get("type") == "notebook":
            data = content if isinstance(content, dict) else {}
            abs_path.write_text(json.dumps(data), encoding="utf-8")
        else:
            payload = content if isinstance(content, str) else json.dumps(content)
            abs_path.write_text(payload, encoding="utf-8")
        return {"path": path, "type": model.get("type")}


@pytest.fixture
def notebook_env(monkeypatch, tmp_path):
    path = "/test.ipynb"

    initial_cells = [
        {
            "id": "cell-1",
            "cell_type": "markdown",
            "source": FakeYText("Hello"),
            "metadata": {},
        },
        {
            "id": "cell-2",
            "cell_type": "code",
            "source": FakeYText("print('hi')"),
            "metadata": {},
        },
    ]
    notebook = FakeNotebook(initial_cells)
    collaboration = FakeCollaboration({path: notebook})
    fake_server = SimpleNamespace(
        web_app=SimpleNamespace(settings={"jupyter_server_ydoc": collaboration}),
        contents_manager=FakeContentsManager(tmp_path),
        root_dir=str(tmp_path),
    )

    monkeypatch.setattr(
        ServerApp,
        "instance",
        classmethod(lambda cls: fake_server),
    )

    return path, notebook


@pytest.mark.asyncio
async def test_list_notebook_cells(notebook_env):
    path, notebook = notebook_env
    payload = json.loads(await list_notebook_cells(path))
    assert payload["kind"] == RICH_OUTPUT_KIND
    assert payload["version"] == RICH_OUTPUT_VERSION
    raw = payload.get("raw") or {}
    assert raw["path"] == path
    assert raw["cell_count"] == len(notebook.ycells)
    assert raw["cells"][0]["id"] == "cell-1"
    assert payload["blocks"], "Expected rich output blocks to be present"


@pytest.mark.asyncio
async def test_get_notebook_cell_source(notebook_env):
    path, _ = notebook_env
    payload = json.loads(await get_notebook_cell_source(path, cell_id="cell-2"))
    assert payload["cell_id"] == "cell-2"
    assert payload["source"] == "print('hi')"


@pytest.mark.asyncio
async def test_insert_notebook_cell_appends_when_index_missing(notebook_env):
    path, notebook = notebook_env
    before = len(notebook.ycells)
    response = json.loads(
        await insert_notebook_cell(path, cell_type="markdown", source="New cell")
    )
    assert len(notebook.ycells) == before + 1
    assert response["index"] == before
    assert _source_to_string(notebook.ycells[-1]["source"]) == "New cell"


@pytest.mark.asyncio
async def test_insert_notebook_cell_with_string_index(notebook_env):
    path, notebook = notebook_env
    await insert_notebook_cell(path, index="1", cell_type="code", source="second")
    assert _source_to_string(notebook.ycells[1]["source"]) == "second"


@pytest.mark.asyncio
async def test_update_notebook_cell_by_id(notebook_env):
    path, notebook = notebook_env
    await update_notebook_cell(path, cell_id="cell-1", source="Updated")
    assert _source_to_string(notebook.ycells[0]["source"]) == "Updated"


@pytest.mark.asyncio
async def test_delete_notebook_cell_by_index(notebook_env):
    path, notebook = notebook_env
    before = len(notebook.ycells)
    response = json.loads(await delete_notebook_cell(path, index=0))
    assert len(notebook.ycells) == before - 1
    assert response["cell_id"] == "cell-1"


@pytest.mark.asyncio
async def test_delete_all_notebook_cells(notebook_env):
    path, notebook = notebook_env
    before = len(notebook.ycells)
    result = json.loads(await delete_all_notebook_cells(path))
    assert result["deleted"] == before
    assert len(notebook.ycells) == 0


@pytest.mark.asyncio
async def test_invalid_path_extension_raises(monkeypatch):
    fake_server = SimpleNamespace(
        web_app=SimpleNamespace(settings={"jupyter_server_ydoc": FakeCollaboration({})})
    )
    monkeypatch.setattr(
        ServerApp,
        "instance",
        classmethod(lambda cls: fake_server),
    )
    with pytest.raises(NotebookToolkitError):
        await list_notebook_cells("/not-a-notebook.txt")


def test_notebook_toolkit_registration():
    tool_names = {tool.name for tool in NOTEBOOK_TOOLKIT.tools}
    expected = {
        "list_notebook_cells",
        "get_notebook_cell_source",
        "ensure_notebook_open_command",
        "create_notebook",
        "insert_notebook_cell",
        "update_notebook_cell",
        "delete_notebook_cell",
        "delete_all_notebook_cells",
        "run_notebook_all_cells",
        "run_notebook_all_above",
        "run_notebook_all_below",
        "run_notebook_cell",
        "run_notebook_cell_and_select_next",
        "run_notebook_cell_and_insert_below",
    }
    assert expected.issubset(tool_names)


def test_build_notebook_open_payload():
    payload = _build_notebook_open_payload("/foo/bar", activate_only=False)
    assert payload["commandId"] == "docmanager:open"
    assert payload["args"]["path"] == "foo/bar.ipynb"
    assert payload["autoApprove"] is True
    assert payload["activate_only"] is False

    payload_activate = _build_notebook_open_payload("/foo/bar", activate_only=True)
    assert payload_activate["commandId"] == "docmanager:activate"
    assert payload_activate["activate_only"] is True


@pytest.mark.asyncio
async def test_ensure_notebook_open_command_dispatch(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_await_frontend_command(command_id: str, **kwargs):
        captured["command_id"] = command_id
        captured["kwargs"] = kwargs
        return {"status": "ok", "result": {"path": kwargs["args"]["path"]}}

    monkeypatch.setattr(
        "jupyter_ai.tools.extended_toolkit.await_frontend_command",
        fake_await_frontend_command,
    )

    result = await ensure_notebook_open_command("/foo/bar")

    assert result["status"] == "ok"
    assert captured["command_id"] == "docmanager:open"
    assert captured["kwargs"]["args"]["path"] == "foo/bar.ipynb"
    assert captured["kwargs"]["metadata"]["activate_only"] is False


@pytest.mark.asyncio
async def test_ensure_notebook_open_command_activate(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_await_frontend_command(command_id: str, **kwargs):
        captured["command_id"] = command_id
        captured["kwargs"] = kwargs
        return {"status": "ok"}

    monkeypatch.setattr(
        "jupyter_ai.tools.extended_toolkit.await_frontend_command",
        fake_await_frontend_command,
    )

    await ensure_notebook_open_command("/foo/bar", activate_only=True, timeout=10)

    assert captured["command_id"] == "docmanager:activate"
    assert captured["kwargs"]["metadata"]["activate_only"] is True


def test_run_notebook_command_payloads():
    payload = json.loads(run_notebook_all_cells("/foo.ipynb"))
    assert payload["commandId"] == "jupyter-ai:run-notebook-action"
    assert payload["args"]["action"] == "run-all-cells"
    assert payload["args"]["path"] == "foo.ipynb"

    above = json.loads(run_notebook_all_above("/foo.ipynb", index="2"))
    assert above["args"]["cellIndex"] == 2
    assert above["args"]["action"] == "run-all-above"
    assert above["args"]["path"] == "foo.ipynb"

    below = json.loads(run_notebook_all_below("/foo.ipynb", cell_id="abc"))
    assert below["args"]["cellId"] == "abc"
    assert below["args"]["action"] == "run-all-below"
    assert below["args"]["path"] == "foo.ipynb"

    single = json.loads(run_notebook_cell("/foo.ipynb"))
    assert single["args"]["action"] == "run-cell"
    assert single["args"]["path"] == "foo.ipynb"

    select_next = json.loads(run_notebook_cell_and_select_next("/foo.ipynb", index=3))
    assert select_next["args"]["cellIndex"] == 3
    assert select_next["args"]["action"] == "run-cell-and-select-next"
    assert select_next["args"]["path"] == "foo.ipynb"

    insert_below = json.loads(run_notebook_cell_and_insert_below("/foo.ipynb", cell_id="cell-1"))
    assert insert_below["args"]["cellId"] == "cell-1"
    assert insert_below["args"]["action"] == "run-cell-and-insert-below"
    assert insert_below["args"]["path"] == "foo.ipynb"


@pytest.mark.asyncio
async def test_create_notebook_creates_file_and_returns_metadata(monkeypatch, tmp_path):
    collaboration = FakeCollaboration({})
    contents_manager = FakeContentsManager(tmp_path)
    fake_server = SimpleNamespace(
        web_app=SimpleNamespace(settings={"jupyter_server_ydoc": collaboration}),
        contents_manager=contents_manager,
        root_dir=str(tmp_path),
    )
    monkeypatch.setattr(
        ServerApp,
        "instance",
        classmethod(lambda cls: fake_server),
    )

    payload = json.loads(await create_notebook("/analysis/new"))
    created_path = tmp_path / "analysis" / "new.ipynb"
    assert created_path.exists()
    assert payload == {"path": "analysis/new.ipynb", "created": True}


@pytest.mark.asyncio
async def test_create_notebook_rejects_existing(monkeypatch, tmp_path):
    existing = tmp_path / "existing.ipynb"
    existing.write_text("{}", encoding="utf-8")

    collaboration = FakeCollaboration({})
    contents_manager = FakeContentsManager(tmp_path)
    fake_server = SimpleNamespace(
        web_app=SimpleNamespace(settings={"jupyter_server_ydoc": collaboration}),
        contents_manager=contents_manager,
        root_dir=str(tmp_path),
    )
    monkeypatch.setattr(
        ServerApp,
        "instance",
        classmethod(lambda cls: fake_server),
    )

    with pytest.raises(NotebookToolkitError):
        await create_notebook("/existing.ipynb")


def test_plan_aware_toolkit_includes_notebook_tools():
    plan_tool_names = {tool.name for tool in PLAN_AWARE_TOOLKIT.tools}
    assert "list_notebook_cells" in plan_tool_names
    assert "run_notebook_cell" in plan_tool_names
