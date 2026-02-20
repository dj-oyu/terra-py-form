"""CLI for terra-py-form."""
import sys

import click

from terra_py_form.cold.parser import Parser
from terra_py_form.cold.graph import Graph
from terra_py_form.cold.planner import Planner
from terra_py_form.cold.state import State


@click.group()
def cli():
    """terra-py-form: Infrastructure as Code tool."""
    pass


@cli.command()
@click.argument("file", type=click.Path(exists=True))
def plan(file):
    """Show planned changes (dry-run).
    
    Reads a YAML file and displays what resources would be created,
    modified, or deleted.
    """
    # Parse file directly
    parser = Parser()
    try:
        parsed = parser.parse(file)
    except Exception as e:
        click.echo(f"Error parsing: {e}", err=True)
        sys.exit(1)

    # Build graph
    graph = Graph(parsed)

    # Plan
    current_state = State()
    planner = Planner(current_state)
    diffs = planner.plan(graph)

    # Display
    if not diffs:
        click.echo("No changes planned.")
        return

    click.echo(f"Planned changes ({len(diffs)}):\n")

    for diff in diffs:
        action_color = {
            "create": "green",
            "update": "yellow",
            "delete": "red",
        }.get(diff.action, "white")

        icon = {
            "create": "+",
            "update": "~",
            "delete": "-",
        }.get(diff.action, "?")

        click.secho(f"  {icon} {diff.resource_name}", fg=action_color)
        click.echo(f"    action: {diff.action}")
        if diff.before:
            click.echo(f"    before: {diff.before}")
        if diff.after:
            click.echo(f"    after: {diff.after}")


@cli.command()
@click.argument("file", type=click.Path(exists=True))
def validate(file):
    """Validate a YAML file without making changes."""
    try:
        parser = Parser()
        parsed = parser.parse(file)
        graph = Graph(parsed)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    click.echo(f"✓ Valid: {file}")
    click.echo(f"  Resources: {len(parsed.resources)}")


def main():
    cli()


if __name__ == "__main__":
    main()
