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

# Register subcommands (signatures defined in cli.py; bodies are stubs until phases land)
app.command()(cli.resolve)
app.command()(cli.logs)
app.command()(cli.ssh)
app.command()(cli.cancel)
app.command()(cli.inspect)
app.command()(cli.pick)
app.command()(cli.top)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
