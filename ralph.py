#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = ["typer>=0.12.0"]
# ///
"""
Ralph loop runner (Python version of the shell template).

Shell template:

  prompt="your prompt here"
  for i in $(seq 1 100); do
    agent --dangerously-skip-permissions -p "$prompt"
  done

Usage:
  uv run --script ralph.py                    # reads PROMPT.md
  uv run --script ralph.py "your prompt here" # override file
  uv run --script ralph.py --interactive      # type/paste prompt, end with Ctrl-D

  uv run --script ralph.py "your prompt here" --iterations 50
  uv run --script ralph.py "your prompt here" --no-change-exit-after 10

  ./ralph.py "your prompt here"      # after: chmod +x ralph.py

Stops early if there are no git changes (no HEAD change and no `git diff` change)
for N consecutive iterations.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import IO, Any, Optional

import typer  # pyright: ignore[reportMissingImports]

DEFAULT_ITERATIONS = 50
DEFAULT_NO_CHANGE_EXIT_AFTER = 10
DEFAULT_PROMPT_FILE = "PROMPT.md"


SubprocessFile = int | IO[Any] | None


def _subprocess_stream_stdio() -> tuple[SubprocessFile, SubprocessFile]:
    """
    Best-effort passthrough so child output shows up live in this terminal.

    Note: `subprocess.run()` already inherits stdout/stderr by default when you
    don't pass `capture_output=True` or redirect streams. We still set it
    explicitly when possible, but fall back safely if stdout/stderr don't expose
    real file descriptors (e.g., some redirected/captured environments).
    """

    try:
        sys.stdout.fileno()
        sys.stderr.fileno()
    except Exception:
        return (None, None)
    return (sys.stdout, sys.stderr)


def _repo_dir() -> Path:
    # `ralph.py` lives in the repo root; anchor git commands here (not the caller's CWD).
    return Path(__file__).resolve().parent


def _resolve_prompt_file(prompt_file: Path, repo_dir: Path) -> Path:
    if prompt_file.is_absolute():
        return prompt_file
    return repo_dir / prompt_file


def _load_prompt(prompt: Optional[str], prompt_file: Path, repo_dir: Path) -> str:
    if prompt is not None:
        if not prompt.strip():
            typer.echo("PROMPT argument cannot be empty.", err=True)
            raise typer.Exit(code=2)
        return prompt

    path = _resolve_prompt_file(prompt_file, repo_dir)
    try:
        contents = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        typer.echo(
            f"Prompt file not found: {path}\n"
            "Create PROMPT.md in the repo root, or pass a PROMPT argument.",
            err=True,
        )
        raise typer.Exit(code=2) from None
    except OSError as e:
        typer.echo(f"Failed to read prompt file {path}: {e}", err=True)
        raise typer.Exit(code=2) from None

    if not contents.strip():
        typer.echo(f"Prompt file {path} is empty.", err=True)
        raise typer.Exit(code=2)

    return contents


def _load_prompt_interactive() -> str:
    if sys.stdin.isatty():
        typer.echo(
            "Enter prompt below. Finish with EOF (Ctrl-D on macOS/Linux; Ctrl-Z then Enter on Windows).",
            err=True,
        )
        typer.echo("", err=True)

    contents = sys.stdin.read()
    if not contents.strip():
        typer.echo("Interactive prompt was empty.", err=True)
        raise typer.Exit(code=2)
    return contents


def _git_bytes(repo_dir: Path, *args: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_dir,
            check=False,
            capture_output=True,
        )
    except FileNotFoundError:
        typer.echo('Could not find "git" on PATH.', err=True)
        raise typer.Exit(code=127) from None

    if completed.returncode != 0:
        stderr = completed.stderr.decode(errors="replace")
        typer.echo(f"git command failed: git {' '.join(args)}\n{stderr}", err=True)
        raise typer.Exit(code=2)

    return completed.stdout


def _git_text(repo_dir: Path, *args: str) -> str:
    return _git_bytes(repo_dir, *args).decode(errors="replace").strip()


def _ensure_git_repo(repo_dir: Path) -> None:
    inside = _git_text(repo_dir, "rev-parse", "--is-inside-work-tree")
    if inside != "true":
        typer.echo(f"Not a git work tree: {repo_dir}", err=True)
        raise typer.Exit(code=2)


def _head_sha(repo_dir: Path) -> Optional[str]:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=repo_dir,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        typer.echo('Could not find "git" on PATH.', err=True)
        raise typer.Exit(code=127) from None

    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _git_state_fingerprint(repo_dir: Path) -> str:
    """
    Content-sensitive fingerprint of the git working state.

    Includes:
    - tracked unstaged diff (git diff)
    - tracked staged diff (git diff --cached)
    - untracked files + their content hashes
    """
    h = hashlib.sha256()

    h.update(b"unstaged\0")
    h.update(
        _git_bytes(
            repo_dir,
            "diff",
            "--no-ext-diff",
            "--binary",
            "--no-color",
        )
    )

    h.update(b"\0staged\0")
    h.update(
        _git_bytes(
            repo_dir,
            "diff",
            "--cached",
            "--no-ext-diff",
            "--binary",
            "--no-color",
        )
    )

    h.update(b"\0untracked\0")
    untracked_raw = _git_bytes(repo_dir, "ls-files", "--others", "--exclude-standard", "-z")
    untracked = [p for p in untracked_raw.split(b"\0") if p]
    for rel_b in sorted(untracked):
        h.update(rel_b)
        h.update(b"\0")

        rel = os.fsdecode(rel_b)
        path = repo_dir / rel
        try:
            if path.is_file():
                h.update(hashlib.sha256(path.read_bytes()).digest())
            else:
                h.update(b"\0" * 32)
        except OSError:
            h.update(b"\0" * 32)
        h.update(b"\0")

    return h.hexdigest()


def cli(
    prompt: Optional[str] = typer.Argument(  # noqa: B008
        None,
        help=f"Prompt to pass to agent. If omitted, reads {DEFAULT_PROMPT_FILE}.",
    ),
    prompt_file: Path = typer.Option(  # noqa: B008
        Path(DEFAULT_PROMPT_FILE),
        "--prompt-file",
        "-f",
        help=f"Prompt file to read when PROMPT is omitted (default: {DEFAULT_PROMPT_FILE}).",
        show_default=True,
    ),
    interactive: bool = typer.Option(  # noqa: B008
        False,
        "--interactive",
        "-i",
        help="Read prompt from stdin interactively (multi-line) before starting.",
        show_default=True,
    ),
    iterations: int = typer.Option(  # noqa: B008
        DEFAULT_ITERATIONS,
        "--iterations",
        "-n",
        min=1,
        help="Maximum number of iterations.",
        show_default=True,
    ),
    agent_bin: str = typer.Option(  # noqa: B008
        "claude",
        "--agent-bin",
        envvar="AGENT_BIN",
        help='agent executable (default: "claude", or $AGENT_BIN).',
        show_default=True,
    ),
    continue_on_error: bool = typer.Option(  # noqa: B008
        True,
        "--continue-on-error/--stop-on-error",
        help="Keep looping even if agent exits non-zero.",
        show_default=True,
    ),
    no_change_exit_after: int = typer.Option(  # noqa: B008
        DEFAULT_NO_CHANGE_EXIT_AFTER,
        "--no-change-exit-after",
        min=0,
        help=(
            "Stop early if there are no git changes (no HEAD change and no `git diff` change) "
            "for N consecutive iterations. Set to 0 to disable."
        ),
        show_default=True,
    ),
) -> None:
    """
    Run agent in a loop.
    """

    repo_dir = _repo_dir()
    _ensure_git_repo(repo_dir)
    if interactive:
        if prompt is not None:
            typer.echo("Do not pass PROMPT when using --interactive.", err=True)
            raise typer.Exit(code=2)
        resolved_prompt = _load_prompt_interactive()
    else:
        resolved_prompt = _load_prompt(prompt, prompt_file, repo_dir)
    previous_head = _head_sha(repo_dir) if no_change_exit_after else None
    previous_fingerprint = _git_state_fingerprint(repo_dir) if no_change_exit_after else ""
    no_change_streak = 0
    stdout, stderr = _subprocess_stream_stdio()

    try:
        for _ in range(1, iterations + 1):
            try:
                completed = (
                    subprocess.run(
                        [agent_bin, "--dangerously-skip-permissions", "-p", resolved_prompt],
                        cwd=repo_dir,
                        check=False,
                        stdout=stdout,
                        stderr=stderr,
                    )
                    if agent_bin == "claude"
                    else subprocess.run(
                        [
                            agent_bin,
                            "exec",
                            "--dangerously-bypass-approvals-and-sandbox",
                            resolved_prompt,
                        ],
                        cwd=repo_dir,
                        check=False,
                        stdout=stdout,
                        stderr=stderr,
                    )
                )
            except FileNotFoundError:
                typer.echo(
                    f'Could not find "{agent_bin}". Is the agent CLI installed and on PATH? '
                    "You can also set $AGENT_BIN.",
                    err=True,
                )
                raise typer.Exit(code=127) from None

            if completed.returncode != 0:
                typer.echo(
                    f"agent exited with status {completed.returncode}.",
                    err=True,
                )
                if not continue_on_error:
                    raise typer.Exit(code=completed.returncode)

            if no_change_exit_after:
                current_head = _head_sha(repo_dir)
                current_fingerprint = _git_state_fingerprint(repo_dir)

                # NOTE: We do NOT stop when HEAD changes; a HEAD change resets the streak.
                if current_head == previous_head and current_fingerprint == previous_fingerprint:
                    no_change_streak += 1
                    if no_change_streak >= no_change_exit_after:
                        typer.echo(
                            f"No git change for {no_change_streak} consecutive iterations; stopping."
                        )
                        return
                else:
                    previous_head = current_head
                    previous_fingerprint = current_fingerprint
                    no_change_streak = 0
    except KeyboardInterrupt:
        # Match typical shell behavior for Ctrl+C.
        typer.echo("", err=True)
        raise typer.Exit(code=130) from None


if __name__ == "__main__":
    typer.run(cli)
