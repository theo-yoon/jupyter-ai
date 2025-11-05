import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "jupyter-ai"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))


def test_repository_singleton_shared():
    from workflow.playbook_flow.repository import PlaybookRunRepository, repository as workflow_repo
    from jupyter_ai.playbook_flow.repository import repository as package_repo

    assert workflow_repo is package_repo
    assert isinstance(workflow_repo, PlaybookRunRepository)


def test_broadcaster_singleton_shared():
    from workflow.playbook_flow.broadcaster import playbook_broadcaster as workflow_broadcaster
    from jupyter_ai.playbook_flow.broadcaster import playbook_broadcaster as package_broadcaster

    assert workflow_broadcaster is package_broadcaster


def test_model_aliases_match():
    from workflow.playbook_flow.models import PlaybookRunResult
    from jupyter_ai.playbook_flow.models import PlaybookRunResult as PackagePlaybookRunResult

    assert PlaybookRunResult is PackagePlaybookRunResult
