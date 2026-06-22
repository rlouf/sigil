"""Command-line entrypoint for the Zeta runtime."""

import json
import sys
from dataclasses import asdict
from pathlib import Path

import click

from zeta.dispatch import queue_item_snapshots, queue_item_status_counts
from zeta.rpc import run_stdio
from zeta.store.events import Filter, SqliteEventStore, event_store_path

QUEUE_STATUS_ORDER = (
    "available",
    "claimed",
    "completed",
    "failed",
    "cancelled",
    "retry_scheduled",
    "unhandled",
)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def cli() -> None:
    """Zeta runtime commands."""


def runtime_state_dir(project_root: Path, state_dir: Path | None) -> Path:
    if state_dir is not None:
        return state_dir.expanduser()
    return project_root.expanduser().resolve() / ".zeta"


def runtime_event_store(project_root: Path, state_dir: Path | None) -> SqliteEventStore:
    return SqliteEventStore(
        event_store_path(runtime_state_dir(project_root, state_dir))
    )


@cli.command("queue")
@click.option(
    "--project-root",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
    help="Project root containing .zeta runtime state.",
)
@click.option(
    "--state-dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Override the runtime state directory.",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON.")
def queue(project_root: Path, state_dir: Path | None, json_output: bool) -> int:
    """List projected runtime queue items."""

    event_store = runtime_event_store(project_root, state_dir)
    try:
        snapshots = queue_item_snapshots(
            event_store.list_events(Filter(event_type_prefix="runtime.queue_item."))
        )
    finally:
        event_store.close()
    if json_output:
        click.echo(
            json.dumps(
                [asdict(snapshot) for snapshot in snapshots],
                ensure_ascii=False,
            )
        )
        return 0
    if not snapshots:
        click.echo("queue empty")
        return 0
    for snapshot in snapshots:
        click.echo(
            "\t".join(
                [
                    snapshot.status,
                    snapshot.queue_item_id,
                    snapshot.target_agent,
                    snapshot.event_id,
                ]
            )
        )
    return 0


@cli.command("status")
@click.option(
    "--project-root",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
    help="Project root containing .zeta runtime state.",
)
@click.option(
    "--state-dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Override the runtime state directory.",
)
def status(project_root: Path, state_dir: Path | None) -> int:
    """Show projected runtime queue counts."""

    event_store = runtime_event_store(project_root, state_dir)
    try:
        snapshots = queue_item_snapshots(
            event_store.list_events(Filter(event_type_prefix="runtime.queue_item."))
        )
    finally:
        event_store.close()
    counts = queue_item_status_counts(snapshots)
    if not counts:
        click.echo("queue empty")
        return 0
    for status_name in QUEUE_STATUS_ORDER:
        count = counts.get(status_name)
        if count is not None:
            click.echo(f"{status_name}: {count}")
    return 0


@cli.command("rpc")
@click.option("--stdio", is_flag=True, help="Serve newline-delimited JSON-RPC.")
def rpc(stdio: bool) -> int:
    """Serve the Zeta JSON-RPC protocol."""
    if not stdio:
        raise click.UsageError("only --stdio is supported")
    run_stdio(sys.stdin, sys.stdout)
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        result = cli.main(args=argv, prog_name="zeta", standalone_mode=False)
    except click.ClickException as error:
        error.show()
        return error.exit_code
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
