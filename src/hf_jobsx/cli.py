"""Subcommand definitions (signatures only; bodies are Phase 0 stubs).

Each command's docstring states which SPEC.md phase implements it. Until then,
every command raises a clear "not implemented" message rather than pretending to work.
"""

from __future__ import annotations

from typing import Annotated

import typer


def _not_implemented(command: str, phase: str) -> None:
    """Honest stub: print and exit non-zero so nobody mistakes a scaffold for working code."""
    typer.echo(
        f"`hf jobsx {command}` is not implemented yet (scaffold only).\n"
        f"See SPEC.md — Phase {phase}.\n"
        f"Source of truth: Projects/HF Jobs/jobsx.md (Obsidian).",
        err=True,
    )
    raise typer.Exit(code=1)


def resolve(
    selector: Annotated[
        list[str],
        typer.Argument(help="One or more selectors to resolve (@N, @latest, @status=…, @label=…, literal id)."),
    ],
    namespace: Annotated[str | None, typer.Option("--namespace", "-n", help="HF namespace (default: whoami).")] = None,
    token: Annotated[str | None, typer.Option("--token", "-t")] = None,
) -> None:
    """Resolve selector(s) to job id(s) with their @N index. The selector REPL. (Phase 1)"""
    _not_implemented("resolve", "1")


def logs(
    selector: Annotated[list[str], typer.Argument(help="Selector resolving to ONE job.")],
    follow: Annotated[bool, typer.Option("-f", "--follow", help="Stream until job completes.")] = False,
    tail: Annotated[int | None, typer.Option("-n", "--tail", help="Last N lines.")] = None,
    namespace: Annotated[str | None, typer.Option("--namespace", "-n")] = None,
    token: Annotated[str | None, typer.Option("--token", "-t")] = None,
) -> None:
    """Resolve selector → exec into native `hf jobs logs -f <id>`. (Phase 1)"""
    _not_implemented("logs", "1")


def ssh(
    selector: Annotated[list[str], typer.Argument(help="Selector resolving to ONE running job.")],
    namespace: Annotated[str | None, typer.Option("--namespace", "-n")] = None,
    token: Annotated[str | None, typer.Option("--token", "-t")] = None,
) -> None:
    """Resolve selector → exec into native `hf jobs ssh <id>`. (Phase 1)"""
    _not_implemented("ssh", "1")


def cancel(
    selector: Annotated[list[str], typer.Argument(help="Selector resolving to ONE job.")],
    yes: Annotated[bool, typer.Option("-y", "--yes", help="Skip confirmation.")] = False,
    namespace: Annotated[str | None, typer.Option("--namespace", "-n")] = None,
    token: Annotated[str | None, typer.Option("--token", "-t")] = None,
) -> None:
    """Resolve selector → native `hf jobs cancel <id>` (confirm if ambiguous). (Phase 1)"""
    _not_implemented("cancel", "1")


def inspect(
    selector: Annotated[list[str], typer.Argument(help="Selector resolving to ONE job.")],
    namespace: Annotated[str | None, typer.Option("--namespace", "-n")] = None,
    token: Annotated[str | None, typer.Option("--token", "-t")] = None,
) -> None:
    """Resolve selector → native `hf jobs inspect <id>`. (Phase 1)"""
    _not_implemented("inspect", "1")


def pick(
    action: Annotated[str, typer.Option("--action", help="logs|ssh|cancel|inspect (default logs).")] = "logs",
    namespace: Annotated[str | None, typer.Option("--namespace", "-n")] = None,
    token: Annotated[str | None, typer.Option("--token", "-t")] = None,
) -> None:
    """Interactive jump-picker → exec into the chosen action. (Phase 2)"""
    _not_implemented("pick", "2")


def top(
    namespace: Annotated[str | None, typer.Option("--namespace", "-n")] = None,
    refresh: Annotated[float, typer.Option("--refresh", help="Frame interval seconds (default 0.75).")] = 0.75,
    token: Annotated[str | None, typer.Option("--token", "-t")] = None,
) -> None:
    """Dense live monitor: sparklines + inline tail-log + @N indexes. (Phase 3) ⭐"""
    _not_implemented("top", "3")
