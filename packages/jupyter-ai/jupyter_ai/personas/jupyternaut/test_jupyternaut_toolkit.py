"""Tests for Jupyternaut persona tooling."""

from ...tools.document_toolkit import DOCUMENT_TOOLKIT
from .jupyternaut import JUPYTERNAUT_TOOLKIT


def test_document_tools_registered():
    document_tool_names = {tool.name for tool in DOCUMENT_TOOLKIT.get_tools()}
    persona_tool_names = {tool.name for tool in JUPYTERNAUT_TOOLKIT.get_tools()}

    assert document_tool_names.issubset(persona_tool_names)
