import json
import os
import pathlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .models import Tool, Toolkit

@dataclass
class DocumentQueryMatch:
    """
    Represents a relevant fragment returned from a document query.
    """

    location: str
    snippet: str
    score: float


@dataclass
class DocumentQueryResult:
    """
    Container returned by document query strategies.
    """

    document: str
    question: str
    strategy: str
    matches: list[DocumentQueryMatch]
    message: str | None = None


class BaseDocumentStrategy(ABC):
    """
    Abstract base class for document query strategies.
    """

    name: str = "base"

    @abstractmethod
    def supports(self, path: pathlib.Path) -> bool:
        """
        Returns True if this strategy can handle the target file.
        """

    @abstractmethod
    def query(self, path: pathlib.Path, question: str, max_results: int) -> DocumentQueryResult:
        """
        Returns a structured response describing relevant fragments.
        """


class JSONDocumentStrategy(BaseDocumentStrategy):
    """
    Query strategy for JSON documents.
    """

    name = "json"
    _SUPPORTED_SUFFIXES = {".json", ".geojson", ".ipynb"}

    def supports(self, path: pathlib.Path) -> bool:
        return path.suffix.lower() in self._SUPPORTED_SUFFIXES

    def query(self, path: pathlib.Path, question: str, max_results: int) -> DocumentQueryResult:
        document = _load_json(path)

        keywords = _extract_keywords(question)
        flattened = list(_flatten_json(document))
        matches = _rank_fragments(flattened, keywords, max_results)

        message = None
        if not matches:
            message = "No matching entries were found. Returning the first fragments in document order."
            matches = _rank_fragments(flattened, set(), max_results)

        return DocumentQueryResult(
            document=str(path),
            question=question,
            strategy=self.name,
            matches=matches,
            message=message,
        )


class PlainTextDocumentStrategy(BaseDocumentStrategy):
    """
    Fallback strategy for text-like documents.
    """

    name = "plain-text"

    def supports(self, path: pathlib.Path) -> bool:
        return True

    def query(self, path: pathlib.Path, question: str, max_results: int) -> DocumentQueryResult:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        keywords = _extract_keywords(question)

        scored_segments: list[tuple[str, str, float]] = []
        for idx, line in enumerate(lines):
            line_tokens = set(_tokenize(line))
            score = sum(1 for kw in keywords if kw in line_tokens)
            if score > 0:
                location = f"line {idx + 1}"
                snippet = _truncate(line.strip())
                scored_segments.append((location, snippet, float(score)))

        matches = [
            DocumentQueryMatch(location=loc, snippet=snip, score=score)
            for loc, snip, score in sorted(scored_segments, key=lambda item: (-item[2], item[0]))
        ][:max_results]

        message = None
        if not matches:
            message = "No keyword matches were found. Returning the first lines for reference."
            matches = [
                DocumentQueryMatch(location=f"line {idx + 1}", snippet=_truncate(line.strip()), score=0.0)
                for idx, line in enumerate(lines[:max_results])
            ]

        return DocumentQueryResult(
            document=str(path),
            question=question,
            strategy=self.name,
            matches=matches,
            message=message,
        )


class QnaJSONDocumentStrategy(BaseDocumentStrategy):
    """
    Specialized strategy for QnA-style JSON files containing structured FAQ entries.
    """

    name = "qna-json"
    _SUPPORTED_SUFFIXES = {".json", ".qna"}
    _KNOWN_FIELDS = (
        "TITLE",
        "CONTENT",
        "COMMENT_SET",
        "CATEGORY_NAME",
        "MAJOR_CATEGORY",
        "SUB_CATEGORY",
    )

    def supports(self, path: pathlib.Path) -> bool:
        return path.suffix.lower() in self._SUPPORTED_SUFFIXES

    def query(self, path: pathlib.Path, question: str, max_results: int) -> DocumentQueryResult:
        data = _load_json(path)
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise ValueError("QnA JSON documents must be a list of objects.")

        keywords = _extract_keywords(question)
        matches: list[DocumentQueryMatch] = []

        for index, item in enumerate(data):
            text_parts = [
                str(item.get(field, "")).strip()
                for field in self._KNOWN_FIELDS
                if item.get(field)
            ]
            combined_text = " ".join(text_parts)
            if not combined_text:
                continue

            tokens = set(_tokenize(combined_text))
            score = float(sum(1 for kw in keywords if kw in tokens))
            if keywords and score == 0:
                continue

            title = str(item.get("TITLE") or f"entry[{index}]")
            matches.append(
                DocumentQueryMatch(
                    location=title,
                    snippet=_truncate(combined_text),
                    score=score,
                )
            )

        message: str | None = None
        if not matches:
            message = "No QnA entries matched the question. Returning the first entries for reference."
            for index, item in enumerate(data[:max_results]):
                text_parts = [
                    str(item.get(field, "")).strip()
                    for field in self._KNOWN_FIELDS
                    if item.get(field)
                ]
                combined_text = " ".join(text_parts) or json.dumps(item, ensure_ascii=True)
                title = str(item.get("TITLE") or f"entry[{index}]")
                matches.append(
                    DocumentQueryMatch(
                        location=title,
                        snippet=_truncate(combined_text),
                        score=0.0,
                    )
                )

        matches.sort(key=lambda match: (-match.score, match.location))
        matches = matches[:max_results]

        return DocumentQueryResult(
            document=str(path),
            question=question,
            strategy=self.name,
            matches=matches,
            message=message,
        )


def _flatten_json(data: Any, prefix: str | None = None) -> Iterable[tuple[str, Any]]:
    """
    Recursively flattens a JSON object into path/value pairs.
    """
    if isinstance(data, dict):
        for key, value in data.items():
            child_prefix = f"{prefix}.{key}" if prefix else key
            yield from _flatten_json(value, child_prefix)
    elif isinstance(data, list):
        for index, value in enumerate(data):
            child_prefix = f"{prefix}[{index}]" if prefix else f"[{index}]"
            yield from _flatten_json(value, child_prefix)
    else:
        path = prefix or ""
        yield (path, data)


def _rank_fragments(
    fragments: Sequence[tuple[str, Any]],
    keywords: set[str],
    max_results: int,
) -> list[DocumentQueryMatch]:
    candidates: list[DocumentQueryMatch] = []
    for location, value in fragments:
        value_text = _stringify_value(value)
        tokens = set(_tokenize(location)) | set(_tokenize(value_text))
        if keywords:
            score = float(sum(1 for kw in keywords if kw in tokens))
            if score == 0:
                continue
        else:
            score = 0.0
        candidates.append(
            DocumentQueryMatch(
                location=location,
                snippet=_truncate(value_text),
                score=score,
            )
        )

    candidates.sort(key=lambda match: (-match.score, match.location))
    return candidates[:max_results]


def _extract_keywords(question: str) -> set[str]:
    return set(_tokenize(question))


def _tokenize(text: str) -> list[str]:
    return [token for token in re.findall(r"[A-Za-z0-9_]+", text.lower()) if len(token) > 2]


def _stringify_value(value: Any) -> str:
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=True)


def _truncate(text: str, limit: int = 240) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _load_json(path: pathlib.Path) -> Any:
    raw_text = path.read_text(encoding="utf-8")
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Unable to parse JSON document: {path}") from exc


_STRATEGIES: list[BaseDocumentStrategy] = [
    QnaJSONDocumentStrategy(),
    JSONDocumentStrategy(),
    PlainTextDocumentStrategy(),
]


def _resolve_document_path(
    document_path: str | None,
    *,
    default_filename: str = "qna.json",
    extra_roots: Sequence[pathlib.Path] | None = None,
) -> pathlib.Path:
    """
    Resolves the document path used by qna_document.

    The supplied path may point to a file directly, to a directory that contains
    a default document, or it may omit a path entirely. When the path cannot be
    resolved directly, a search is performed across known locations, including
    the current working directory and any entries in the
    ``JUPYTER_AI_DOCUMENT_PATHS`` environment variable (path-separated).
    """
    raw_path = (document_path or "").strip()
    if not raw_path:
        raw_path = default_filename

    path = pathlib.Path(raw_path).expanduser()

    direct = _resolve_direct_path(path, default_filename)
    if direct:
        return direct

    search_names = _build_candidate_names(path, default_filename)
    search_roots = _build_search_roots(path, extra_roots)

    for root in search_roots:
        for name in search_names:
            candidate = root / name
            if candidate.is_file():
                try:
                    return candidate.resolve()
                except OSError:
                    return candidate

    raise FileNotFoundError(f"Document not found. Tried: {', '.join(str(root / name) for root in search_roots for name in search_names)}")


def _resolve_direct_path(path: pathlib.Path, default_filename: str) -> pathlib.Path | None:
    if path.is_file():
        try:
            return path.resolve()
        except OSError:
            return path

    if path.is_dir():
        candidate = path / default_filename
        if candidate.is_file():
            try:
                return candidate.resolve()
            except OSError:
                return candidate
        raise FileNotFoundError(f"Document not found: {candidate}")

    if path.is_absolute():
        raise FileNotFoundError(f"Document not found: {path}")

    return None


def _build_candidate_names(path: pathlib.Path, default_filename: str) -> list[str]:
    names: list[str] = []
    path_name = path.name

    if path_name and path_name != ".":
        names.append(path_name)

    if default_filename not in names:
        names.append(default_filename)

    return names


def _build_search_roots(path: pathlib.Path, extra_roots: Sequence[pathlib.Path] | None = None) -> list[pathlib.Path]:
    roots: list[pathlib.Path] = []

    # If the provided path has a relative parent (e.g. "docs/qna.json"), include it.
    if not path.is_absolute():
        parent = path if path.is_dir() else path.parent
        if parent and str(parent) not in ("", "."):
            candidate = pathlib.Path.cwd() / parent
            roots.append(candidate)

    # Include current working directory.
    roots.append(pathlib.Path.cwd())

    # Include user-provided search paths.
    env_paths = os.environ.get("JUPYTER_AI_DOCUMENT_PATHS", "")
    for raw in env_paths.split(os.pathsep):
        if not raw:
            continue
        candidate = pathlib.Path(raw).expanduser()
        roots.append(candidate)

    if extra_roots:
        roots.extend(extra_roots)

    # Deduplicate while preserving order
    unique_roots: list[pathlib.Path] = []
    seen: set[pathlib.Path] = set()
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            resolved = root
        if resolved in seen:
            continue
        seen.add(resolved)
        unique_roots.append(root)

    return unique_roots


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=True)


def qna_document(question: str, max_results: int = 5) -> str:
    """
    Search QnA-oriented documents for information relevant to the question and
    return a summarized answer.

    Parameters
    ----------
    question : str
        Natural language description of the information to retrieve.
    max_results : int, optional
        Maximum number of fragments to include in the response. Defaults to 5.

    Returns
    -------
    str
        Human-readable summary of relevant information sourced from the nearest
        QnA document. Includes the document path and excerpts for the top
        matches.
    """
    if max_results < 1:
        raise ValueError("max_results must be at least 1")

    try:
        path = _resolve_document_path(None)
    except FileNotFoundError as exc:
        return (
            "I could not locate a QnA document. "
            "Set the environment variable JUPYTER_AI_DOCUMENT_PATHS or place "
            "a qna.json file in the current workspace.\n"
            f"Details: {exc}"
        )

    last_error: ValueError | None = None
    result: DocumentQueryResult | None = None
    for strategy in _STRATEGIES:
        if strategy.supports(path):
            try:
                result = strategy.query(path, question, max_results)
                break
            except ValueError as exc:
                last_error = exc
                continue

    if result is None:
        if last_error:
            return f"Failed to read the QnA document: {last_error}"
        return "I could not process the QnA document with any available strategy."

    return _format_summary(result)


DOCUMENT_TOOLKIT = Toolkit(
    name="jupyter-ai-document-toolkit",
    description="Tools for extracting structured information from documents.",
)
DOCUMENT_TOOLKIT.add_tool(Tool(callable=qna_document, read=True))


def _format_summary(result: DocumentQueryResult) -> str:
    lines: list[str] = [
        f"Document: {result.document}",
    ]

    if result.matches:
        lines.append("Top matches:")
        for match in result.matches:
            lines.append(f"- {match.location}: {match.snippet}")
    else:
        lines.append("No relevant entries were found.")

    if result.message:
        lines.append("")
        lines.append(result.message)

    return "\n".join(lines)


CLOUD_PLAYBOOK_FILENAME = "cloud_playbook.json"
JUPYTERLAB_PLAYBOOK_FILENAME = "jupyterlab_playbook.json"

_PLAYBOOK_REGISTRY: dict[str, dict[str, Any]] = {
    "cloud": {
        "filename": CLOUD_PLAYBOOK_FILENAME,
        "display_name": "cloud playbook",
        "missing_message": "I could not locate the cloud playbook. Ensure cloud_playbook.json is available or set JUPYTER_AI_DOCUMENT_PATHS.",
        "no_match_message": "I did not find a matching cloud incident. Try rephrasing the issue or update the playbook.",
    },
    "jupyterlab": {
        "filename": JUPYTERLAB_PLAYBOOK_FILENAME,
        "display_name": "JupyterLab playbook",
        "missing_message": "I could not locate the JupyterLab playbook. Ensure jupyterlab_playbook.json is available or set JUPYTER_AI_DOCUMENT_PATHS.",
        "no_match_message": "I did not find a matching JupyterLab topic. Try rephrasing the request or update the playbook.",
    },
}


def cloud_playbook(question: str, max_results: int = 3) -> str:
    """
    Consult the built-in cloud operations playbook and summarize recommended actions.
    """
    return _lookup_playbook("cloud", question, max_results)


DOCUMENT_TOOLKIT.add_tool(Tool(callable=cloud_playbook, read=True))


def jupyterlab_playbook(question: str, max_results: int = 3) -> str:
    """
    Consult the JupyterLab usage playbook and summarize recommended steps.
    """
    return _lookup_playbook("jupyterlab", question, max_results)


DOCUMENT_TOOLKIT.add_tool(Tool(callable=jupyterlab_playbook, read=True))


def _lookup_playbook(playbook_key: str, question: str, max_results: int) -> str:
    if max_results < 1:
        raise ValueError("max_results must be at least 1")

    config = _PLAYBOOK_REGISTRY.get(playbook_key)
    if config is None:
        raise ValueError(f"Unknown playbook: {playbook_key}")

    filename = config["filename"]
    missing_message = config.get("missing_message", f"I could not locate the {playbook_key} playbook.")
    no_match_message = config.get("no_match_message", "I did not find a matching entry in this playbook.")
    document_hint = config.get("document_hint", filename)
    extra_root_specs = config.get("extra_roots", [])

    data_dir = pathlib.Path(__file__).parent / "data"
    extra_roots: list[pathlib.Path] = [data_dir]
    for root in extra_root_specs:
        extra_roots.append(pathlib.Path(root))

    try:
        path = _resolve_document_path(
            document_hint,
            default_filename=filename,
            extra_roots=extra_roots,
        )
    except FileNotFoundError as exc:
        return f"{missing_message}\nDetails: {exc}"

    entries = _load_playbook_entries(path)
    results = _search_playbook(entries, question, max_results)
    if not results:
        return f"Playbook source: {path}\n{no_match_message}"

    primary = results[0]
    automation_payload = _maybe_build_automation(primary, path)
    response_summary = _format_playbook_response(path, results)

    if automation_payload:
        automation_payload.setdefault("message", _format_playbook_entry(primary))
        automation_payload["result"] = response_summary
        return json.dumps(automation_payload)

    return response_summary


def _load_playbook_entries(path: pathlib.Path) -> list[dict[str, Any]]:
    raw = _load_json(path)
    if not isinstance(raw, list):
        raise ValueError("Cloud playbook must contain a list of entries.")
    entries: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            entries.append(item)
    return entries


def _search_playbook(
    entries: Sequence[dict[str, Any]],
    question: str,
    max_results: int,
) -> list[dict[str, Any]]:
    keywords = _extract_keywords(question)
    scored: list[tuple[float, dict[str, Any]]] = []
    for entry in entries:
        tokens = _collect_playbook_tokens(entry)
        if not tokens:
            continue
        score = float(sum(1 for kw in keywords if kw in tokens))
        if keywords and score == 0:
            continue
        scored.append((score, entry))

    scored.sort(key=lambda item: (-item[0], (item[1].get("title") or item[1].get("TITLE") or "")))
    return [entry for _, entry in scored[:max_results]]


def _format_playbook_response(path: pathlib.Path, entries: Sequence[dict[str, Any]]) -> str:
    lines: list[str] = [
        f"Playbook source: {path}",
    ]

    for entry in entries:
        lines.append("")
        lines.append(_format_playbook_entry(entry))

    return "\n".join(lines)


def _format_playbook_entry(entry: dict[str, Any]) -> str:
    title = _stringify(entry.get("title") or entry.get("TITLE") or "Unnamed scenario")
    service = _stringify(entry.get("service") or entry.get("SERVICE") or "")
    severity = _stringify(entry.get("severity") or "")
    taxonomy = entry.get("taxonomy") or {}
    domain = _stringify(taxonomy.get("domain"))
    category = _stringify(taxonomy.get("category"))
    subcategory = _stringify(taxonomy.get("subcategory"))

    header_parts = [title]
    qualifiers = []
    if service:
        qualifiers.append(f"Service: {service}")
    if severity:
        qualifiers.append(f"Severity: {severity}")
    if domain:
        taxonomy_parts = [domain]
        if category:
            taxonomy_parts.append(category)
        if subcategory:
            taxonomy_parts.append(subcategory)
        qualifiers.append(f"Domain: {' / '.join(taxonomy_parts)}")
    if qualifiers:
        header_parts.append(" — " + ", ".join(qualifiers))
    header = "".join(header_parts)

    def _format_list(name: str, values: Sequence[str] | None) -> list[str]:
        if not values:
            return []
        cleaned = [v for v in values if v]
        if not cleaned:
            return []
        return [f"  {name}:"]
    body_lines = [f"- {header}"]

    def _append_items(label: str, values: Sequence[Any] | str | None) -> None:
        if not values:
            return
        iterable: Sequence[Any]
        if isinstance(values, str):
            iterable = [values]
        else:
            iterable = values
        items: list[str] = []
        for value in iterable:
            if isinstance(value, dict):
                desc = _stringify(value.get("description") or value.get("desc") or "")
                phase = value.get("phase")
                if phase:
                    desc = f"[{phase}] {desc}"
                if desc:
                    items.append(desc)
            else:
                text = _stringify(value)
                if text:
                    items.append(text)
        if not items:
            return
        body_lines.append(f"  {label}:")
        for item in items:
            body_lines.append(f"    - {item}")

    _append_items("Preconditions", entry.get("preconditions") or entry.get("PRECONDITIONS"))
    _append_items("Symptoms", entry.get("symptoms") or entry.get("SYMPTOMS"))
    _append_items("Diagnostics", entry.get("diagnostics") or entry.get("CHECKS"))
    _append_items("Actions", entry.get("actions") or entry.get("RESOLUTION"))
    _append_items("Post-checks", entry.get("postChecks") or entry.get("POST_CHECKS"))
    metrics = entry.get("metrics") or entry.get("METRICS")
    if metrics:
        metric_text = ", ".join(str(metric) for metric in metrics if metric)
        if metric_text:
            body_lines.append(f"  Metrics: {metric_text}")
    escalation = entry.get("escalation") or entry.get("ESCALATION")
    if escalation:
        if isinstance(escalation, dict):
            condition = escalation.get("condition")
            contact = escalation.get("contact")
            esc_parts = []
            if condition:
                esc_parts.append(f"When {condition}")
            if contact:
                esc_parts.append(f"contact {contact}")
            if esc_parts:
                body_lines.append(f"  Escalation: {'; '.join(esc_parts)}")
        else:
            body_lines.append(f"  Escalation: {escalation}")
    notes = entry.get("notes") or entry.get("COMMENT_SET")
    if notes:
        note_items = notes if isinstance(notes, list) else [notes]
        note_text = "; ".join(str(n) for n in note_items if n)
        if note_text:
            body_lines.append(f"  Notes: {note_text}")
    references = entry.get("references")
    if isinstance(references, list) and references:
        body_lines.append("  References:")
        for ref in references:
            if isinstance(ref, dict):
                label = ref.get("label") or "Reference"
                url = ref.get("url")
                if url:
                    body_lines.append(f"    - {label}: {url}")
                else:
                    body_lines.append(f"    - {label}")
            else:
                body_lines.append(f"    - {ref}")

    return "\n".join(body_lines)


def _maybe_build_automation(entry: dict[str, Any], path: pathlib.Path) -> dict[str, Any] | None:
    possible_sources: list[dict[str, Any]] = []
    actions = entry.get("actions")
    if isinstance(actions, list):
        possible_sources.extend(a for a in actions if isinstance(a, dict))
    diagnostics = entry.get("diagnostics")
    if isinstance(diagnostics, list):
        possible_sources.extend(d for d in diagnostics if isinstance(d, dict))
    for item in possible_sources:
        automation = item.get("automation")
        if not isinstance(automation, dict):
            continue
        if automation.get("type") != "command":
            continue
        payload = automation.get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                continue
        if not isinstance(payload, dict):
            continue
        data = json.loads(json.dumps(payload))
        data.setdefault("type", "jupyterlab-command")
        message = automation.get("message") or payload.get("message") or item.get("description")
        if message:
            data["message"] = message
        extras = data.setdefault("extras", {})
        extras["playbookSource"] = str(path)
        phase = item.get("phase")
        if phase:
            extras["playbookPhase"] = phase
        extras["playbookId"] = entry.get("id") or entry.get("ID")
        return data
    return None


def _collect_playbook_tokens(entry: dict[str, Any]) -> set[str]:
    text_parts: list[str] = []

    for key in ("id", "title", "service", "severity"):
        value = entry.get(key) or entry.get(key.upper())
        if value:
            text_parts.append(_stringify(value))

    taxonomy = entry.get("taxonomy")
    if isinstance(taxonomy, dict):
        for key in ("domain", "category", "subcategory"):
            value = taxonomy.get(key)
            if value:
                text_parts.append(_stringify(value))

    for key in ("preconditions", "symptoms", "postChecks", "notes", "metrics"):
        values = entry.get(key) or entry.get(key.upper())
        if isinstance(values, list):
            text_parts.extend(_stringify(v) for v in values if v)
        elif values:
            text_parts.append(_stringify(values))

    escalation = entry.get("escalation") or entry.get("ESCALATION")
    if isinstance(escalation, dict):
        for key in ("condition", "contact"):
            value = escalation.get(key)
            if value:
                text_parts.append(_stringify(value))
    elif escalation:
        text_parts.append(_stringify(escalation))

    def _collect_from_list(values):
        if isinstance(values, list):
            for item in values:
                if isinstance(item, dict):
                    desc = item.get("description") or item.get("desc")
                    if desc:
                        text_parts.append(_stringify(desc))
                    phase = item.get("phase")
                    if phase:
                        text_parts.append(_stringify(phase))
                    label = item.get("label")
                    if label:
                        text_parts.append(_stringify(label))
                    url = item.get("url")
                    if url:
                        text_parts.append(_stringify(url))
                elif item:
                    text_parts.append(_stringify(item))
        elif values:
            text_parts.append(_stringify(values))

    _collect_from_list(entry.get("diagnostics") or entry.get("CHECKS"))
    _collect_from_list(entry.get("actions") or entry.get("RESOLUTION"))
    _collect_from_list(entry.get("references"))

    tokens: set[str] = set()
    for part in text_parts:
        for token in _tokenize(part):
            tokens.add(token)
    return tokens
