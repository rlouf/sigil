"""Model profile commands."""

import os

import click
from zeta.models.profiles import (
    clear_active_model_profile,
    load_model_profiles,
    resolve_model_profile,
    set_active_model_profile,
)

from commas.cli._base import cli, examples
from commas.sessions import session_dir


@cli.group(
    "model",
    epilog=examples(
        "commas model use deep",
        "commas model clear",
    ),
)
def cmd_model() -> None:
    """Switch Zeta model profiles for this shell session.

    Profiles are defined in ~/.zeta/models.toml. The selection is scoped to
    the current shell session, so other terminals keep their own; without a
    selection, the `default = true` profile applies, then the builtin local
    default.
    """


@cmd_model.command(
    "use",
    epilog=examples(
        "commas model use deep",
        'commas model use fast && , "why did the last command fail?"',
    ),
)
@click.argument("name")
def cmd_model_use(name: str) -> int:
    """Use the NAME profile for the current shell session.

    NAME is a profile from ~/.zeta/models.toml. The selection sticks until
    `commas model clear`; other sessions are unaffected.
    """
    catalog = load_model_profiles()
    for diagnostic in catalog.diagnostics:
        click.echo(f"model config: {diagnostic.message}", err=True)
    selection = resolve_model_profile(name, catalog=catalog)
    if selection is None:
        raise click.ClickException(f"unknown model profile: {name}")
    set_active_model_profile(selection.profile, session_dir=session_dir())
    click.echo(f"model: {selection.profile} -> {selection.model} @ {selection.url}")
    if not os.environ.get("COMMAS_SESSION_ID"):
        click.echo(
            'no shell session detected; the selection applies to session "default"',
            err=True,
        )
    return 0


@cmd_model.command(
    "clear",
    epilog=examples("commas model clear"),
)
def cmd_model_clear() -> int:
    """Clear the session's model selection.

    The session returns to the `default = true` profile, or to the builtin
    local default when no profile claims the flag.
    """
    removed = clear_active_model_profile(session_dir=session_dir())
    if removed:
        click.echo("model: cleared")
    else:
        click.echo("model: default")
    return 0
