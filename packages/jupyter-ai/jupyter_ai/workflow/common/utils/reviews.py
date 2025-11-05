from __future__ import annotations

import re
from typing import Tuple, List


def parse_review_message(message: str | None) -> Tuple[str | None, List[str]]:
    """
    Extract a summary and follow-up actions from a review-style freeform message.
    """
    lines = [
        line.strip()
        for line in (message or "").splitlines()
        if line.strip()
    ]
    if not lines:
        return None, []
    summary = lines[0]
    actions: list[str] = []
    for line in lines[1:]:
        stripped = line.lstrip("-*•0123456789.). ").strip()
        if not stripped:
            continue
        if line.startswith(('- ', '* ', '• ', '– ')):
            actions.append(stripped)
            continue
        if re.match(r"^\d+[\.)]\s+", line):
            actions.append(stripped)
            continue
        prefix = stripped.lower()
        if prefix.startswith(('next', 'todo', 'follow', 'after', 'continue')):
            actions.append(stripped)
    return summary, actions
