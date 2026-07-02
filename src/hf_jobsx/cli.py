"""Subcommand definitions. (SPEC §1)

Design stance: dumb pipe, smart edges. jobsx owns selection/addressing and DELEGATES
depth to native `hf jobs` via os.execvp (process replacement — native takes over
stdout/stdin, so `logs -f` streaming and `ssh` interactivity work natively).
"""

from __future__ import annotations

import os
import shlex
import shutil
import sys
from typing import Annotated

import typer

from hf_jobsx import runspec
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
    """Resolve a selector to one job and follow its logs (streams native `hf jobs logs`)."""
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
    """Resolve a selector to one running job and SSH into it (`hf jobs ssh`)."""
    client, job = _require_single_or_die(selector, namespace=namespace, token=token)
    typer.echo(f"jobsx: ssh {job.id}  {stage_str(job)}  {display_name(job)}", err=True)
    _exec_native(_native_argv("ssh", job.id, extra=[], namespace=client.namespace, token=token))


def cancel(
    selector: Annotated[list[str], typer.Argument(help="Selector resolving to ONE job.")],
    yes: Annotated[bool, typer.Option("-y", "--yes", help="Skip confirmation.")] = False,
    namespace: Annotated[str | None, typer.Option("--namespace", "-n")] = None,
    token: Annotated[str | None, typer.Option("--token", "-t")] = None,
) -> None:
    """Resolve a selector to one job and cancel it (`hf jobs cancel`). Asks to confirm."""
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
    """Resolve a selector to one job and show its details (`hf jobs inspect`)."""
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
    """Interactive jump-picker — fuzzy-filter the job list, then jump into logs/ssh.

    (Not yet implemented.)
    """
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
    """Dense live monitor: per-job CPU/GPU/net sparklines, status, runtime, ~cost,
    and the inline last log line. Drill into logs/ssh with a keypress, return with Ctrl-C.

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


def _parse_env_overrides(items: list[str] | None) -> dict[str, str]:
    """Parse repeated ``-e KEY=VALUE`` overrides into a dict."""
    out: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            _die(f"--env expects KEY=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        out[key] = value
    return out


def run(
    script: Annotated[
        str,
        typer.Argument(
            # \[ escapes the bracket so Rich renders it literally, not as a markup tag.
            help="UV script to launch: a local .py path or an https URL. Its "
            r"\[tool.hf-jobs] header (if any) sets the runtime."
        ),
    ],
    script_args: Annotated[
        list[str] | None,
        typer.Argument(help="Arguments passed through to the script (unknown flags too)."),
    ] = None,
    image: Annotated[
        str | None, typer.Option("--image", help="Override the Docker image from the header.")
    ] = None,
    flavor: Annotated[
        str | None, typer.Option("--flavor", help="Override the hardware flavor from the header.")
    ] = None,
    python: Annotated[
        str | None,
        typer.Option("-p", "--python", help="Override the interpreter from the header."),
    ] = None,
    timeout: Annotated[
        str | None,
        typer.Option(
            "--timeout",
            # timeout is a per-run cost decision (scales with your data), not a header key.
            help="Max duration for this run, e.g. 2h, 90m (default 30m). A per-run flag, "
            "not a header key.",
        ),
    ] = None,
    env: Annotated[
        list[str] | None,
        typer.Option("-e", "--env", help="Add/override an env var KEY=VALUE (repeatable)."),
    ] = None,
    secrets: Annotated[
        list[str] | None,
        typer.Option("-s", "--secrets", help="Forward a secret NAME to the job (repeatable)."),
    ] = None,
    detach: Annotated[
        bool, typer.Option("-d", "--detach", help="Run in the background and print the job id.")
    ] = False,
    namespace: Annotated[str | None, typer.Option("--namespace")] = None,
    token: Annotated[str | None, typer.Option("--token")] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Print the resolved `hf jobs uv run` command and exit; launch nothing.",
        ),
    ] = False,
) -> None:
    r"""Launch a UV script on HF Jobs, applying its `\[tool.hf-jobs]` runtime header.

    Some recipes must run on a specific image/interpreter/PYTHONPATH or they fail
    silently (every output row an error sentinel). This reads the runtime block that
    travels with the script — image, flavor, python, env, secrets — so you don't have
    to remember the launch flags. Explicit flags here override the header; the real
    launch is delegated to native `hf jobs uv run`.
    """
    try:
        header = runspec.parse_runtime(runspec.read_script_text(script, token=token))
    except ValueError as e:
        _die(str(e))
    except Exception as e:  # network / permission — surface a clean one-liner
        _die(f"could not read script {script!r}: {_friendly_error(e)}")

    overrides = {
        "image": image,
        "flavor": flavor,
        "python": python,
        "env": _parse_env_overrides(env),
        "secrets": secrets or [],
    }
    try:
        # Header shapes were validated at parse time; this catches the remainder
        # (e.g. an --env override value native's dotenv parser can't round-trip).
        resolved = runspec.resolve(header, overrides)
    except ValueError as e:
        _die(str(e))

    for warning in resolved.warnings:
        typer.secho(f"jobsx: {warning}", err=True, fg=typer.colors.YELLOW)
    if resolved.echo:
        typer.secho("jobsx: resolved runtime (header + overrides):", err=True, fg=typer.colors.CYAN)
        for line in resolved.echo:
            typer.echo(f"  {line}", err=True)
    else:
        typer.secho(
            "jobsx: no [tool.hf-jobs] block — passing through to native hf jobs uv run",
            err=True,
            fg=typer.colors.BRIGHT_BLACK,
        )

    argv = ["hf", "jobs", "uv", "run", *resolved.flags]
    # timeout is a per-run flag, not a header key — pass it straight through to native.
    if timeout:
        argv += ["--timeout", timeout]
    if detach:
        argv.append("--detach")
    if namespace:
        argv += ["--namespace", namespace]
    if token:
        argv += ["--token", token]
    argv += [script, *(script_args or [])]

    if dry_run:
        typer.echo(shlex.join(argv))
        raise typer.Exit()
    _exec_native(argv)
