"""Tests for document_toolkit.py."""

import json
import pathlib
import pytest

from .document_toolkit import (
    CLOUD_PLAYBOOK_FILENAME,
    DOCUMENT_TOOLKIT,
    JUPYTERLAB_PLAYBOOK_FILENAME,
    cloud_playbook,
    jupyterlab_playbook,
    qna_document,
)


def _prepare_workspace(tmp_path, monkeypatch, filename="qna.json", content="") -> str:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    doc_path = workspace / filename
    doc_path.write_text(content, encoding="utf-8")
    monkeypatch.chdir(workspace)
    return str(doc_path)


class TestQnaDocument:
    def test_returns_ranked_qna_matches(self, tmp_path, monkeypatch):
        records = [
            {
                "TITLE": "Password Reset",
                "CONTENT": "Follow the security portal instructions to reset your password.",
                "COMMENT_SET": "support",
                "CATEGORY_NAME": "Account",
                "MAJOR_CATEGORY": "Access",
                "SUB_CATEGORY": "Credentials",
            },
            {
                "TITLE": "Data Pipeline Monitoring",
                "CONTENT": "Use the monitoring dashboard to review daily pipeline metrics.",
                "COMMENT_SET": "operations",
                "CATEGORY_NAME": "Data",
                "MAJOR_CATEGORY": "Operations",
                "SUB_CATEGORY": "Monitoring",
            },
        ]
        doc_path = _prepare_workspace(tmp_path, monkeypatch, content=json.dumps(records))

        answer = qna_document("How do I monitor the data pipeline?", max_results=2)

        assert f"Document: {doc_path}" in answer
        assert "- Data Pipeline Monitoring" in answer
        assert "dashboard" in answer.lower()

    def test_handles_generic_json_documents(self, tmp_path, monkeypatch):
        payload = {
            "company": {"name": "Acme Analytics", "hq": "New York"},
            "employees": [
                {"name": "Alice", "role": "Data Scientist", "location": "New York"},
                {"name": "Bob", "role": "DevOps Engineer", "location": "Seoul"},
            ],
        }
        doc_path = _prepare_workspace(tmp_path, monkeypatch, content=json.dumps(payload))

        answer = qna_document("Who is the data scientist?", max_results=2)

        assert f"Document: {doc_path}" in answer
        assert "employees[0].role" in answer
        assert "data scientist" in answer.lower()

    def test_plain_text_fallback(self, tmp_path, monkeypatch):
        content = "\n".join(
            [
                "Meeting recap for Q1 initiatives.",
                "The data pipelines need additional monitoring and automation.",
                "Budget approvals remain pending.",
            ]
        )
        doc_path = _prepare_workspace(tmp_path, monkeypatch, content=content)

        answer = qna_document("How are data pipelines doing?", max_results=2)

        assert f"Document: {doc_path}" in answer
        assert "- line 2" in answer
        assert "data pipelines" in answer.lower()

    def test_max_results_validation(self):
        with pytest.raises(ValueError):
            qna_document("Any info?", max_results=0)

    def test_missing_document_message(self, tmp_path, monkeypatch):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        monkeypatch.chdir(workspace)

        answer = qna_document("Where is the FAQ?")

        assert "could not locate a qna document" in answer.lower()

    def test_environment_search_paths(self, tmp_path, monkeypatch):
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        doc_path = docs_dir / "qna.json"
        doc_path.write_text(json.dumps({"faq": []}), encoding="utf-8")

        monkeypatch.setenv("JUPYTER_AI_DOCUMENT_PATHS", str(docs_dir))
        monkeypatch.chdir(tmp_path)

        answer = qna_document("question?")

        assert f"Document: {doc_path}" in answer

    def test_relative_directory_resolution(self, tmp_path, monkeypatch):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        docs_dir = workspace / "docs"
        docs_dir.mkdir()
        doc_path = docs_dir / "qna.json"
        doc_path.write_text(json.dumps({"faq": []}), encoding="utf-8")

        monkeypatch.chdir(workspace)

        answer = qna_document("question?")

        assert f"Document: {doc_path}" in answer


class TestDocumentToolkitRegistration:
    def test_document_toolkit_contains_tools(self):
        tool_names = {tool.name for tool in DOCUMENT_TOOLKIT.get_tools()}
        assert "qna_document" in tool_names
        assert "cloud_playbook" in tool_names
        assert "jupyterlab_playbook" in tool_names


class TestCloudPlaybookTool:
    def test_defaults_to_packaged_playbook(self):
        answer = cloud_playbook("latency spike", max_results=2)
        assert CLOUD_PLAYBOOK_FILENAME in answer
        assert "latency" in answer.lower()

    def test_environment_override(self, tmp_path, monkeypatch):
        data = [
            {
                "id": "custom-incident",
                "title": "Custom Incident",
                "service": "Test Service",
                "version": 1,
                "lastReviewed": "2025-01-15",
                "severity": "low",
                "taxonomy": {
                    "domain": "general",
                    "category": "testing",
                    "subcategory": "debug"
                },
                "symptoms": ["Custom symptom"],
                "diagnostics": [{"description": "Check dashboards"}],
                "actions": [{"phase": "mitigation", "description": "Restart service"}],
                "postChecks": [],
                "preconditions": [],
                "metrics": [],
                "notes": [],
                "escalation": {"condition": "", "contact": ""}
            }
        ]
        playbook = tmp_path / "cloud_playbook.json"
        playbook.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setenv("JUPYTER_AI_DOCUMENT_PATHS", str(tmp_path))

        answer = cloud_playbook("custom symptom")

        assert "Custom Incident" in answer
        assert "Restart service" in answer

    def test_handles_no_match(self, tmp_path, monkeypatch):
        data_dir = pathlib.Path(__file__).parent / "data"
        monkeypatch.setenv("JUPYTER_AI_DOCUMENT_PATHS", str(data_dir))
        answer = cloud_playbook("unknown issue", max_results=1)
        assert "did not find a matching incident" in answer.lower()

    def test_automation_returns_command(self, tmp_path, monkeypatch):
        data = [
            {
                "id": "notebook-debug",
                "title": "Create Troubleshooting Notebook",
                "service": "JupyterLab",
                "version": 1,
                "lastReviewed": "2025-01-15",
                "severity": "low",
                "taxonomy": {
                    "domain": "operations",
                    "category": "tooling",
                    "subcategory": "notebook"
                },
                "symptoms": ["Need a fresh notebook to debug."],
                "diagnostics": [],
                "actions": [
                    {
                        "phase": "mitigation",
                        "description": "Open a new notebook and document findings.",
                        "automation": {
                            "type": "command",
                            "payload": {
                                "type": "jupyterlab-command",
                                "commandId": "docmanager:new-untitled",
                                "args": {"path": "/", "type": "notebook"},
                                "summary": "Create debugging notebook",
                                "message": "Notebook created for debugging.",
                                "successMessage": "Notebook ready."
                            }
                        }
                    }
                ],
                "postChecks": [],
                "preconditions": [],
                "metrics": [],
                "notes": [],
                "escalation": {"condition": "", "contact": ""}
            }
        ]
        playbook = tmp_path / "cloud_playbook.json"
        playbook.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setenv("JUPYTER_AI_DOCUMENT_PATHS", str(tmp_path))
        monkeypatch.chdir(tmp_path)

        answer = cloud_playbook("debugging notebook", max_results=1)
        payload = json.loads(answer)
        assert payload["type"] == "jupyterlab-command"
        assert payload["commandId"] == "docmanager:new-untitled"
        assert "Notebook created" in payload["message"]
        assert "Playbook source" in payload["result"]


class TestJupyterLabPlaybookTool:
    def test_defaults_to_packaged_playbook(self):
        answer = jupyterlab_playbook("how do i create a notebook?", max_results=2)
        assert JUPYTERLAB_PLAYBOOK_FILENAME in answer
        assert "Create a new notebook" in answer

    def test_automation_payload(self):
        answer = jupyterlab_playbook("create notebook", max_results=1)
        payload = json.loads(answer)
        assert payload["type"] == "jupyterlab-command"
        assert payload["commandId"] == "docmanager:new-untitled"
        assert "Playbook source" in payload["result"]

    def test_no_match(self, tmp_path, monkeypatch):
        data_dir = pathlib.Path(__file__).parent / "data"
        monkeypatch.setenv("JUPYTER_AI_DOCUMENT_PATHS", str(data_dir))
        answer = jupyterlab_playbook("unknown jupyter feature", max_results=1)
        assert "playbook source" in answer.lower()
