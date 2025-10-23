import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jupyter_server.serverapp import ServerApp

from .notebook_toolkit import (
    NOTEBOOK_TOOLKIT,
    NotebookToolkitError,
    create_notebook,
    delete_notebook_cell,
    delete_all_notebook_cells,
    get_notebook_cell_source,
    insert_notebook_cell,
    list_notebook_cells,
    ensure_notebook_open_command,
    update_notebook_cell,
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
    result = json.loads(await list_notebook_cells(path))
    assert result["path"] == path
    assert result["cell_count"] == len(notebook.ycells)
    assert result["cells"][0]["id"] == "cell-1"


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
    }
    assert expected.issubset(tool_names)


def test_ensure_notebook_open_command_payload():
    payload = json.loads(ensure_notebook_open_command("/foo/bar.ipynb"))
    assert payload["commandId"] == "docmanager:open"
    assert payload["args"]["path"] == "/foo/bar.ipynb"
    assert "Open notebook" in payload["summary"]

    payload_activate = json.loads(
        ensure_notebook_open_command("/foo/bar.ipynb", activate_only=True)
    )
    assert payload_activate["commandId"] == "docmanager:activate"


@pytest.mark.asyncio
async def test_create_notebook_creates_file_and_returns_command(monkeypatch, tmp_path):
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

    payload = json.loads(await create_notebook("/analysis/new.ipynb"))
    created_path = tmp_path / "analysis" / "new.ipynb"
    assert created_path.exists()
    assert payload["type"] == "jupyterlab-command"
    assert payload["autoApprove"] is True
    assert payload["args"]["path"] == "/analysis/new.ipynb"
    assert payload["summary"].startswith("Open new notebook")


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
