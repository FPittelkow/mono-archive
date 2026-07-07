from __future__ import annotations

from pathlib import Path

import typer

from mono_archive.tui import run


app = typer.Typer(help="Organise, manage and archive mono projects.")


@app.callback(invoke_without_command=True)
def main(
    directory: Path = typer.Argument(
        Path("."),
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        help="Directory to create or load projects from.",
    ),
) -> None:
    run(directory)


if __name__ == "__main__":
    app()
