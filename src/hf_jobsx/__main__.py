"""Console-script entry point. Registered as `hf-jobsx` in pyproject.toml.

`hf jobsx ...` (via the extension system) invokes this. It runs a standalone typer
app — extensions do NOT run inside the native `hf` typer app.
"""

import typer

from hf_jobsx import cli

app = typer.Typer(
    name="jobsx",
    help="Ergonomic HF Jobs CLI extension: jump-picker, selectors, dense live monitor.",
    no_args_is_help=True,
)

# Register subcommands (resolve/logs/ssh/cancel/inspect/top/run implemented; pick is a stub)
app.command()(cli.resolve)
app.command()(cli.logs)
app.command()(cli.ssh)
app.command()(cli.cancel)
app.command()(cli.inspect)
app.command()(cli.pick)
app.command()(cli.top)
# `run` has a docker-style boundary: launch flags go BEFORE the script; the first
# positional token is the script, and everything after it — known or unknown, flag or
# not — passes to the script verbatim (allow_interspersed_args=False stops option
# parsing at the first positional). Unknown flags before the script are a loud
# usage error, never silently bound as the script path.
app.command(context_settings={"allow_interspersed_args": False})(cli.run)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
