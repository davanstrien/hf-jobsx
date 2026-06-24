"""Subcommand definitions. (SPEC §1)

Design stance: dumb pipe, smart edges. jobsx owns selection/addressing and DELEGATES
depth to native `hf jobs` via os.execvp (process replacement — native takes over
stdout/stdin, so `logs -f` streaming and `ssh` interactivity work natively).
"""

from __future__ import annotations

import os
import shutil
import sys
from typing import Annotated

import typer

from hf_jobsx.jobs_client import get_client
from hf_jobsx.selectors import (
    SelectorError,
    display_name,
    flavor_str,
    fmt_duration,
    require_single,
    resolve_indexed,
    stage_str,
)

# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _die(message: str, *, code: int = 1) -> None:
    """Print error to stderr and exit. Never a traceback for user-facing errors."""
    typer.secho(f"jobsx: {message}", err=True, fg=typer.colors.RED)
    raise typer.Exit(code=code)


def _resolve_or_die(specs: list[str], *, namespace: str | None, token: str | None):
    """Fetch jobs, resolve selectors to (index, job) pairs. Handles SelectorError."""
    client = get_client(namespace=namespace, token=token)
    try:
        jobs = client.list_jobs()
    except Exception as e:  # auth/network/HTTP — surface a clean message
        _die(_friendly_error(e))
    try:
        return client, resolve_indexed(specs, jobs, namespace=client.namespace)
    except SelectorError as e:
        _die(str(e))


def _require_single_or_die(specs: list[str], *, namespace: str | None, token: str | None):
    client = get_client(namespace=namespace, token=token)
    try:
        jobs = client.list_jobs()
    except Exception as e:
        _die(_friendly_error(e))
    try:
        return client, require_single(specs, jobs, namespace=client.namespace)
    except SelectorError as e:
        _die(str(e))


def _friendly_error(e: Exception) -> str:
    """Turn common HF errors into a one-line message the user can act on."""
    name = type(e).__name__
    msg = str(e).strip() or "unknown error"
    if "LocalTokenNotFound" in name or "token" in msg.lower():
        return "not logged in. Run `hf auth login`."
    return f"{name}: {msg}"


def _native_argv(
    cmd: str, job_id: str, *, extra: list[str], namespace: str, token: str | None
) -> list[str]:
    """Build the argv for `hf jobs <cmd> <id> [extra]`, propagating namespace/token."""
    argv = ["hf", "jobs", cmd, job_id, "--namespace", namespace, *extra]
    if token:
        argv += ["--token", token]
    return argv


def _exec_native(argv: list[str]) -> None:
    """Replace this process with native `hf`. If `hf` isn't on PATH, fall back to module."""
    hf = shutil.which("hf")
    try:
        if hf:
            os.execvp(hf, argv)
        else:
            # Extension always runs under a Python that has huggingface_hub; use the module.
            python = sys.executable
            os.execvp(python, [python, "-m", "huggingface_hub.cli.hf", *argv[1:]])
    except FileNotFoundError as e:
        _die(f"could not exec native hf: {e}")


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #


def resolve(
    selector: Annotated[
        list[str],
        typer.Argument(
            help="Selector(s): @N, @latest, @status=…, @label=…, @running, @me, or job id."
        ),
    ],
    namespace: Annotated[
        str | None, typer.Option("--namespace", "-n", help="HF namespace (default: whoami).")
    ] = None,
    token: Annotated[str | None, typer.Option("--token", "-t")] = None,
) -> None:
    """Resolve selector(s) to job(s) with their @N index. The selector REPL.

    Pass `@me` (or no match narrowing) to see the whole indexed list with @N assigned.
    """
    _client, pairs = _resolve_or_die(selector, namespace=namespace, token=token)
    if not pairs:
        typer.echo("no jobs match.")
        return
    for index, job in pairs:
        typer.echo(
            f"@{index:<3} {job.id}  {stage_str(job):<10} {flavor_str(job):<14} "
            f"{fmt_duration(job):<6} {display_name(job)}"
        )


def logs(
    selector: Annotated[list[str], typer.Argument(help="Selector resolving to ONE job.")],
    follow: Annotated[
        bool, typer.Option("-f", "--follow", help="Stream until job completes.")
    ] = False,
    tail: Annotated[
        int | None, typer.Option("--tail", help="Last N lines (passed to native hf jobs logs).")
    ] = None,
    namespace: Annotated[str | None, typer.Option("--namespace", "-n")] = None,
    token: Annotated[str | None, typer.Option("--token", "-t")] = None,
) -> None:
    """Resolve selector → exec into native `hf jobs logs -f <id>`. (Phase 1)"""
    client, job = _require_single_or_die(selector, namespace=namespace, token=token)
    extra = []
    if follow:
        extra.append("-f")
    if tail is not None:
        extra += ["-n", str(tail)]
    typer.echo(f"jobsx: {job.id}  {stage_str(job)}  {display_name(job)}", err=True)
    _exec_native(_native_argv("logs", job.id, extra=extra, namespace=client.namespace, token=token))


def ssh(
    selector: Annotated[list[str], typer.Argument(help="Selector resolving to ONE running job.")],
    namespace: Annotated[str | None, typer.Option("--namespace", "-n")] = None,
    token: Annotated[str | None, typer.Option("--token", "-t")] = None,
) -> None:
    """Resolve selector → exec into native `hf jobs ssh <id>`. (Phase 1)"""
    client, job = _require_single_or_die(selector, namespace=namespace, token=token)
    typer.echo(f"jobsx: ssh {job.id}  {stage_str(job)}  {display_name(job)}", err=True)
    _exec_native(_native_argv("ssh", job.id, extra=[], namespace=client.namespace, token=token))


def cancel(
    selector: Annotated[list[str], typer.Argument(help="Selector resolving to ONE job.")],
    yes: Annotated[bool, typer.Option("-y", "--yes", help="Skip confirmation.")] = False,
    namespace: Annotated[str | None, typer.Option("--namespace", "-n")] = None,
    token: Annotated[str | None, typer.Option("--token", "-t")] = None,
) -> None:
    """Resolve selector → native `hf jobs cancel <id>`. (Phase 1)"""
    client, job = _require_single_or_die(selector, namespace=namespace, token=token)
    if not yes:
        confirm = typer.confirm(
            f"Cancel {job.id} ({stage_str(job)}, {display_name(job)})?", default=False
        )
        if not confirm:
            typer.echo("aborted.")
            raise typer.Exit()
    _exec_native(_native_argv("cancel", job.id, extra=[], namespace=client.namespace, token=token))


def inspect(
    selector: Annotated[list[str], typer.Argument(help="Selector resolving to ONE job.")],
    namespace: Annotated[str | None, typer.Option("--namespace", "-n")] = None,
    token: Annotated[str | None, typer.Option("--token", "-t")] = None,
) -> None:
    """Resolve selector → native `hf jobs inspect <id>`. (Phase 1)"""
    client, job = _require_single_or_die(selector, namespace=namespace, token=token)
    typer.echo(f"jobsx: inspect {job.id}", err=True)
    _exec_native(_native_argv("inspect", job.id, extra=[], namespace=client.namespace, token=token))


def pick(
    action: Annotated[
        str, typer.Option("--action", help="logs|ssh|cancel|inspect (default logs).")
    ] = "logs",
    namespace: Annotated[str | None, typer.Option("--namespace", "-n")] = None,
    token: Annotated[str | None, typer.Option("--token", "-t")] = None,
) -> None:
    """Interactive jump-picker → exec into the chosen action. (Phase 2)"""
    typer.echo("`hf jobsx pick` is not implemented yet (Phase 2). See SPEC.md.", err=True)
    raise typer.Exit(code=1)


def top(
    namespace: Annotated[str | None, typer.Option("--namespace", "-n")] = None,
    refresh: Annotated[
        float, typer.Option("--refresh", help="Frame interval seconds (default 0.75).")
    ] = 0.75,
    limit: Annotated[int, typer.Option("--limit", help="Max jobs to display (default 12).")] = 12,
    all_jobs: Annotated[
        bool, typer.Option("--all", help="Show all jobs, not just running (default: running only).")
    ] = False,
    token: Annotated[str | None, typer.Option("--token", "-t")] = None,
) -> None:
    """Dense live monitor: sparklines + inline tail-log + @N indexes. (Phase 3) ⭐

    By default shows only RUNNING jobs (a monitor is for active work). Pass --all to
    include scheduling/error/completed jobs too. Press j/k to move, Enter for logs,
    s for ssh, q to quit.
    """
    from hf_jobsx.fake import fake_client, is_fake_enabled
    from hf_jobsx.render import run_top

    if is_fake_enabled():
        client = fake_client(token=token, namespace=namespace)
    else:
        client = get_client(namespace=namespace, token=token)
    run_top(client=client, refresh=refresh, limit=limit, running_only=not all_jobs)
