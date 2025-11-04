import asyncio
import os
import pathlib
from typing import Any, Dict, Optional

from jupyter_server.serverapp import ServerApp

from .models import Tool, Toolkit
from .tool_payloads import build_tool_payload
from .jlab_command_tool import (
    ensure_notebook_open_command,
    wait_for_notebook_idle,
    select_notebook_cell_command,
    run_notebook_cell_command,
    create_notebook,
    edit_notebook_cell,
    get_notebook_structure,
    find_notebook_cell_by_pattern,
    preview_notebook_cell_edit,
    insert_notebook_cell_command,
    update_notebook_cell_command,
)


def _get_server_root() -> pathlib.Path:
    """
    Return the Jupyter Server contents root directory.

    Falls back to the current working directory if the server instance is
    unavailable (e.g., during unit tests).
    """

    try:
        server = ServerApp.instance()
    except Exception:
        server = None

    if server is not None:
        contents_manager = getattr(server, "contents_manager", None)
        root_dir = getattr(contents_manager, "root_dir", None)
        if isinstance(root_dir, str) and root_dir:
            return pathlib.Path(root_dir).resolve()

    return pathlib.Path.cwd().resolve()


def get_workspace_root() -> pathlib.Path:
    """
    Public helper returning the Jupyter workspace root.

    Provided for backwards compatibility with earlier releases and used by
    other helper modules (e.g., data tools).
    """
    server_root = _get_server_root()
    env_root = os.environ.get("JUPYTER_AI_ROOT_DIR")
    if env_root:
        try:
            return pathlib.Path(env_root).expanduser().resolve()
        except Exception:
            pass
    return server_root


def _resolve_user_path(file_path: str) -> pathlib.Path:
    """
    Resolve ``file_path`` relative to the Jupyter workspace root.

    The helper honours ``JUPYTER_AI_ROOT_DIR`` when available so the agent works in
    restricted sandboxes. All resolved paths are confined to that root; attempting to
    traverse outside raises ``PermissionError``.
    """

    root = get_workspace_root()
    candidate = pathlib.Path(file_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()

    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise PermissionError(
            f"Access to paths outside the workspace root is not allowed: {candidate}"
        ) from exc

    return candidate


def read(file_path: str, offset: int, limit: int) -> str:
    """
    Read a subset of lines from a text file.

    Parameters
    ----------
    file_path : str
        Absolute path to the file that should be read.
    offset : int
        The line number at which to start reading (1-based indexing).
    limit : int
        Number of lines to read starting from *offset*.  
        If *offset + limit* exceeds the number of lines in the file,
        all available lines after *offset* are returned.

    Returns
    -------
    List[str]
        List of lines (including line-ending characters) that were read.

    Examples
    --------
    >>> # Suppose ``/tmp/example.txt`` contains 10 lines
    >>> read('/tmp/example.txt', offset=3, limit=4)
    ['third line\n', 'fourth line\n', 'fifth line\n', 'sixth line\n']
    """
    path = _resolve_user_path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Normalize arguments
    offset = max(1, int(offset))
    limit = max(0, int(limit))
    lines: list[str] = []

    with path.open(encoding='utf-8', errors='replace') as f:
        # Skip to offset
        line_no = 0
        # Loop invariant: line_no := last read line
        # After the loop exits, line_no == offset - 1, meaning the
        # next line starts at `offset`
        while line_no < offset - 1:
            line = f.readline()
            # Return early if offset exceeds number of lines in file
            if line == "":
                return ""
            line_no += 1
        
        # Append lines until limit is reached
        while len(lines) < limit:
            line = f.readline()
            if line == "":
                break
            lines.append(line)

    return "".join(lines)


def edit(
    file_path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> None:
    """
    Replace occurrences of a substring in a file.

    Parameters
    ----------
    file_path : str
        Absolute path to the file that should be edited.
    old_string : str
        Text that should be replaced.
    new_string : str
        Text that will replace *old_string*.
    replace_all : bool, optional
        If ``True`` all occurrences of *old_string* are replaced.
        If ``False`` (default), only the first occurrence in the file is replaced.

    Returns
    -------
    None

    Raises
    ------
    FileNotFoundError
        If *file_path* does not exist.
    ValueError
        If *old_string* is empty (replacing an empty string is ambiguous).

    Notes
    -----
    The file is overwritten atomically: it is first read into memory,
    the substitution is performed, and the file is written back.
    This keeps the operation safe for short to medium-sized files.

    Examples
    --------
    >>> # Replace only the first occurrence
    >>> edit('/tmp/test.txt', 'foo', 'bar', replace_all=False)
    >>> # Replace all occurrences
    >>> edit('/tmp/test.txt', 'foo', 'bar', replace_all=True)
    """
    path = _resolve_user_path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    if old_string == "":
        raise ValueError("old_string must not be empty")

    # Read the entire file
    content = path.read_text(encoding="utf-8", errors="replace")

    # Perform replacement
    if replace_all:
        new_content = content.replace(old_string, new_string)
    else:
        new_content = content.replace(old_string, new_string, 1)

    # Write back
    path.write_text(new_content, encoding="utf-8")


def write(file_path: str, content: str) -> None:
    """
    Write content to a file, creating it if it doesn't exist.

    Parameters
    ----------
    file_path : str
        Absolute path to the file that should be written.
    content : str
        Content to write to the file.

    Returns
    -------
    None

    Raises
    ------
    OSError
        If the file cannot be written (e.g., permission denied, invalid path).

    Notes
    -----
    This function will overwrite the file if it already exists.
    The parent directory must exist; this function does not create directories.

    Examples
    --------
    >>> write('/tmp/example.txt', 'Hello, world!')
    >>> write('/tmp/data.json', '{"key": "value"}')
    """
    path = _resolve_user_path(file_path)
    
    # Write the content to the file
    path.write_text(content, encoding="utf-8")


async def search_grep(pattern: str, include: str = "*") -> Dict[str, Any]:
    """
    Search for text patterns in files using ripgrep.

    This function uses ripgrep (rg) to perform fast regex-based text searching
    across files, with optional file filtering based on glob patterns.

    Parameters
    ----------
    pattern : str
        A regular expression pattern to search for. Ripgrep uses Rust regex
        syntax which supports:
        - Basic regex features: ., *, +, ?, ^, $, [], (), |
        - Character classes: \w, \d, \s, \W, \D, \S
        - Unicode categories: \p{L}, \p{N}, \p{P}, etc.
        - Word boundaries: \b, \B
        - Anchors: ^, $, \A, \z
        - Quantifiers: {n}, {n,}, {n,m}
        - Groups: (pattern), (?:pattern), (?P<name>pattern)
        - Lookahead/lookbehind: (?=pattern), (?!pattern), (?<=pattern), (?<!pattern)
        - Flags: (?i), (?m), (?s), (?x), (?U)
        
        Note: Ripgrep uses Rust's regex engine, which does NOT support:
        - Backreferences (use --pcre2 flag for this)
        - Some advanced PCRE features
    include : str, optional
        A glob pattern to filter which files to search. Defaults to "*" (all files).
        Glob patterns follow gitignore syntax:
        - * matches any sequence of characters except /
        - ? matches any single character except /
        - ** matches any sequence of characters including /
        - [abc] matches any character in the set
        - {a,b} matches either "a" or "b"
        - ! at start negates the pattern
        Examples: "*.py", "**/*.js", "src/**/*.{ts,tsx}", "!*.test.*"

    Returns
    -------
    dict
        Structured payload describing the ripgrep invocation and its matches.

    Raises
    ------
    RuntimeError
        If ripgrep command fails or encounters an error (non-zero exit code).
        This includes cases where:
        - Pattern syntax is invalid
        - Include glob pattern is malformed
        - Ripgrep binary is not available
        - File system errors occur

    Examples
    --------
    >>> search_grep(r"def\s+\w+", "*.py")
    'file.py:10:def my_function():'
    
    >>> search_grep(r"TODO|FIXME", "**/*.{py,js}")
    'app.py:25:# TODO: implement this
    script.js:15:// FIXME: handle edge case'
    
    >>> search_grep(r"class\s+(\w+)", "src/**/*.py")
    'src/models.py:1:class User:'
    """
    # Use bash tool to execute ripgrep
    cmd_parts = ["rg", "--color=never", "--line-number", "--with-filename"]
    
    # Add glob pattern if specified
    if include != "*":
        cmd_parts.extend(["-g", include])
    
    # Add the pattern (always quote it to handle special characters)
    cmd_parts.append(pattern)
    
    # Join command with proper shell escaping
    command = " ".join(f'"{part}"' if " " in part or any(c in part for c in "!*?[]{}()") else part for part in cmd_parts)
    
    try:
        shell_result = await bash(command)
    except Exception as e:
        raise RuntimeError(f"Ripgrep search failed: {str(e)}") from e

    shell_data = shell_result.get("data", {}) if isinstance(shell_result, dict) else {}
    stdout = shell_data.get("stdout", "") if isinstance(shell_data, dict) else ""
    matches: list[Dict[str, Any]] = []
    for line in stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        file_path, line_no, text = parts
        try:
            line_number = int(line_no)
        except ValueError:
            line_number = None
        matches.append(
            {
                "file": file_path,
                "line": line_number,
                "preview": text,
            }
        )

    return build_tool_payload(
        "search.grep",
        {
            "pattern": pattern,
            "include": include,
            "command": shell_data.get("command", command),
            "cwd": shell_data.get("cwd"),
            "matches": matches,
            "match_count": len(matches),
            "stdout": stdout,
            "stderr": shell_data.get("stderr", ""),
            "exit_code": shell_data.get("exit_code"),
            "succeeded": shell_data.get("succeeded"),
        },
        meta={
            "shell": shell_result,
        },
    )


async def bash(command: str, timeout: Optional[int] = None) -> Dict[str, Any]:
    """Executes a bash command and returns the result

    Args:
        command: The bash command to execute
        timeout: Optional timeout in seconds

    Returns:
        Structured payload describing the command execution (stdout/stderr, exit code, cwd, etc.).
    """
    # coerce `timeout` to the correct type. sometimes LLMs pass this as a string
    if isinstance(timeout, str):
        timeout = int(timeout)

    shell_path = os.environ.get("SHELL", "/bin/bash")
    workspace_root = get_workspace_root()

    proc = await asyncio.create_subprocess_exec(
        shell_path,
        "-lc",
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(workspace_root),
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return build_tool_payload(
            "shell.command",
            {
                "command": command,
                "cwd": str(workspace_root),
                "exit_code": None,
                "stdout": "",
                "stderr": "",
                "succeeded": False,
                "timeout": timeout,
            },
            meta={
                "succeeded": False,
                "summary": f"Command timed out after {timeout} seconds",
                "error": "timeout",
            },
        )

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    succeeded = proc.returncode == 0

    summary = stdout.strip() or stderr.strip()
    if summary and len(summary) > 4000:
        summary = summary[:4000] + "…"

    data: Dict[str, Any] = {
        "command": command,
        "cwd": str(workspace_root),
        "exit_code": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "succeeded": succeeded,
        "timeout": timeout,
    }

    meta: Dict[str, Any] = {
        "succeeded": succeeded,
    }
    if summary:
        meta["summary"] = summary

    return build_tool_payload(
        "shell.command",
        data,
        meta=meta,
    )


DEFAULT_TOOLKIT = Toolkit(name="jupyter-ai-default-toolkit")
DEFAULT_TOOLKIT.add_tool(Tool(callable=bash))
DEFAULT_TOOLKIT.add_tool(Tool(callable=read))
DEFAULT_TOOLKIT.add_tool(Tool(callable=edit))
DEFAULT_TOOLKIT.add_tool(Tool(callable=write))
DEFAULT_TOOLKIT.add_tool(Tool(callable=search_grep))
DEFAULT_TOOLKIT.add_tool(
    Tool(callable=ensure_notebook_open_command, execute=True)
)
DEFAULT_TOOLKIT.add_tool(
    Tool(callable=wait_for_notebook_idle, execute=True)
)
DEFAULT_TOOLKIT.add_tool(
    Tool(callable=select_notebook_cell_command, execute=True)
)
DEFAULT_TOOLKIT.add_tool(
    Tool(callable=run_notebook_cell_command, execute=True)
)
DEFAULT_TOOLKIT.add_tool(Tool(callable=edit_notebook_cell, write=True))
DEFAULT_TOOLKIT.add_tool(Tool(callable=create_notebook, execute=True))
DEFAULT_TOOLKIT.add_tool(
    Tool(callable=get_notebook_structure, execute=True)
)
DEFAULT_TOOLKIT.add_tool(
    Tool(callable=find_notebook_cell_by_pattern, execute=True)
)
DEFAULT_TOOLKIT.add_tool(
    Tool(callable=preview_notebook_cell_edit, execute=True)
)
DEFAULT_TOOLKIT.add_tool(
    Tool(callable=insert_notebook_cell_command, write=True)
)
DEFAULT_TOOLKIT.add_tool(
    Tool(callable=update_notebook_cell_command, write=True)
)
