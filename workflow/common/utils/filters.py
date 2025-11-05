from __future__ import annotations

import json
import re
from typing import Tuple


def strip_token(text: str, token: str) -> Tuple[str, bool]:
    if not isinstance(text, str) or not text:
        return text, False
    pattern = re.compile(re.escape(token), re.IGNORECASE)
    if not pattern.search(text):
        return text, False
    cleaned = pattern.sub("", text).strip()
    return cleaned, True


def strip_sentinel(text: str, sentinel: str) -> Tuple[str, bool]:
    if not isinstance(text, str) or not text:
        return text, False
    if sentinel not in text:
        return text, False
    return text.replace(sentinel, "").strip(), True


def format_review_line(value: object) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)
