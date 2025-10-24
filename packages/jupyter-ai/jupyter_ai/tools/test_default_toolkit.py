import json
from pathlib import Path

import pytest

from .default_toolkit import list_workspace


@pytest.mark.parametrize("include_hidden", [False, True])
def test_list_workspace(monkeypatch, tmp_path: Path, include_hidden: bool) -> None:
    monkeypatch.setenv("JUPYTER_AI_ROOT_DIR", str(tmp_path))
    (tmp_path / "analysis.ipynb").write_text("", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("", encoding="utf-8")
    hidden = tmp_path / ".scratch.ipynb"
    hidden.write_text("", encoding="utf-8")

    result = json.loads(list_workspace(include_hidden=include_hidden))
    names = {entry["path"] for entry in result["entries"]}
    assert "analysis.ipynb" in names
    assert "notes.txt" in names
    assert (".scratch.ipynb" in names) is include_hidden


def test_list_workspace_pattern(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("JUPYTER_AI_ROOT_DIR", str(tmp_path))
    (tmp_path / "a.ipynb").write_text("", encoding="utf-8")
    (tmp_path / "b.txt").write_text("", encoding="utf-8")

    result = json.loads(list_workspace(pattern="*.ipynb"))
    names = [entry["path"] for entry in result["entries"]]
    assert names == ["a.ipynb"]
