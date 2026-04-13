#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Run the FastAPI backend and the Vite SPA dev server side by side.

Intended invocation: ``uv run scripts/dev.py``.

Both subprocesses share the parent stdio so logs interleave in one terminal,
each line prefixed with ``[api]`` or ``[web]``.  Ctrl+C (SIGINT) is forwarded
to both children and the script blocks until they exit so no orphan ports
are left behind.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import IO

LOGGER = logging.getLogger("dev")
REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = REPO_ROOT / "web"


def _stream(prefix: str, color: str, stream: IO[str]) -> None:
    """Pipe one child's stdout into the parent terminal with a colored tag."""

    reset = "\033[0m"
    for raw_line in iter(stream.readline, ""):
        line = raw_line.rstrip()
        sys.stdout.write(f"{color}[{prefix}]{reset} {line}\n")
        sys.stdout.flush()


def _spawn(
    *,
    name: str,
    color: str,
    cmd: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.Popen[str]:
    """Start one child process and pump its stdio onto a tagged stream."""

    LOGGER.info("spawning %s: %s (cwd=%s)", name, " ".join(cmd), cwd)
    process = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env={**os.environ, **(env or {})},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    threading.Thread(
        target=_stream,
        args=(name, color, process.stdout),
        daemon=True,
    ).start()
    return process


def _ensure_web_deps_installed() -> None:
    """Run `bun install` once if node_modules is missing — first-time sugar."""

    node_modules = WEB_DIR / "node_modules"
    if node_modules.exists():
        return
    LOGGER.info("web/node_modules missing — running 'bun install' first")
    subprocess.run(["bun", "install"], cwd=str(WEB_DIR), check=True)


def main(argv: list[str] | None = None) -> int:
    """Spawn FastAPI + Vite, mirror their logs, and join cleanly on Ctrl+C."""

    parser = argparse.ArgumentParser(prog="dev", description=__doc__)
    parser.add_argument("--api-port", default="8000")
    parser.add_argument("--web-port", default="5173")
    parser.add_argument(
        "--no-reload",
        action="store_true",
        help=(
            "Disable backend hot-reload. Backend reload kills Playwright "
            "sessions on every save so the next request pays login latency; "
            "use this flag for live-debug sessions where that matters."
        ),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    _ensure_web_deps_installed()

    children: list[subprocess.Popen[str]] = []
    try:
        api_cmd = [
            "uv",
            "run",
            "paris-tennis-webapp",
            "--port",
            str(args.api_port),
        ]
        if not args.no_reload:
            api_cmd.append("--reload")
        children.append(
            _spawn(
                name="api",
                color="\033[38;5;204m",  # Paris-red-ish
                cmd=api_cmd,
                cwd=REPO_ROOT,
            )
        )
        children.append(
            _spawn(
                name="web",
                color="\033[38;5;79m",  # Court-green-ish
                cmd=["bun", "run", "dev", "--port", str(args.web_port)],
                cwd=WEB_DIR,
            )
        )

        sys.stdout.write(
            "\n  → API  http://127.0.0.1:" + str(args.api_port) + "/api\n"
            "  → Web  http://127.0.0.1:" + str(args.web_port) + "/  (use this URL)\n"
            "  Ctrl+C to stop both.\n\n"
        )
        sys.stdout.flush()

        # Block until any child exits, then propagate the shutdown so we
        # never leak a half-running pair of processes.  Polling with a tiny
        # sleep keeps the loop responsive without busy-waiting.
        while True:
            for process in children:
                code = process.poll()
                if code is not None:
                    LOGGER.warning(
                        "child exited with %s — shutting the other down", code
                    )
                    return code or 0
            time.sleep(0.5)

    except KeyboardInterrupt:
        LOGGER.info("Ctrl+C — stopping children")
        return 130
    finally:
        for process in children:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
        for process in children:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                LOGGER.warning("forcing kill on PID %s", process.pid)
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
