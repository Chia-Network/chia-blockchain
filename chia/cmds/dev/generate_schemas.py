from __future__ import annotations

import io
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import click

import chia.apis
from chia.apis import ApiProtocolRegistry
from chia.protocols.outbound_message import NodeType


@click.command("generate-service-peer-schemas")
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(exists=False, path_type=Path),
    default=Path(chia.apis.__file__).parent,
    help="Output directory for generated schema files",
)
@click.option(
    "--service",
    "-s",
    type=click.Choice([node_type.name.lower() for node_type in NodeType]),
    multiple=True,
    help="""Generate schema for specific service(s). Can be used multiple times.
    If not specified, generates for all services.""",
)
@click.option(
    "--format-output/--no-format",
    default=True,
    help="Run ruff format and check --fix on generated files",
)
def generate_service_peer_schemas_cmd(
    output_dir: Path,
    service: tuple[str, ...],
    format_output: bool,
) -> None:
    """Generate service peer API schemas from registered API protocols."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Determine which services to generate
    if service:
        selected_services = [NodeType[name.upper()] for name in service]
    else:
        selected_services = list(ApiProtocolRegistry.keys())

    generated_files = []

    for node_type in selected_services:
        if node_type not in ApiProtocolRegistry:
            click.echo(f"Warning: No API registered for {node_type.name}", err=True)
            continue

        api_class = ApiProtocolRegistry[node_type]
        output_file = output_dir / f"{node_type.name.lower()}_api_schema.py"

        # Generate schema content
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                api_class.metadata.create_schema(api_class)

            schema_content = output.getvalue()

            # Write to file
            with open(output_file, "w") as f:
                f.write(schema_content)

            generated_files.append(output_file)
            click.echo(f"Generated {output_file} ({len(schema_content)} characters)")

        except Exception as e:
            click.echo(f"Error generating schema for {node_type.name}: {e}", err=True)
            continue

    # Format generated files if requested
    if format_output and generated_files:
        _format_files(generated_files)

    if generated_files:
        click.echo(f"Successfully generated {len(generated_files)} schema file(s)")
    else:
        click.echo("No schema files were generated", err=True)
        sys.exit(1)


def _format_files(files: list[Path]) -> None:
    """Format the generated files using ruff."""
    # Find python executable and ruff
    python_exe = sys.executable

    for file_path in files:
        try:
            # Run ruff format
            result = subprocess.run(
                [python_exe, "-m", "ruff", "format", str(file_path)], check=False, capture_output=True, text=True
            )
            if result.returncode == 0:
                click.echo(f"  ✓ Formatted {file_path.name}")
            else:
                click.echo(f"  ✗ ruff format failed for {file_path.name}: {result.stderr}", err=True)

        except Exception as e:
            click.echo(f"  ✗ Failed to format {file_path.name}: {e}", err=True)
            continue

        try:
            # Run ruff check --fix
            result = subprocess.run(
                [python_exe, "-m", "ruff", "check", "--fix", str(file_path)],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                click.echo(f"  ✓ No ruff check issues for {file_path.name}")
            else:
                click.echo(f"  ✓ Fixed ruff check issues for {file_path.name}")

        except Exception as e:
            click.echo(f"  ✗ Failed to run ruff check on {file_path.name}: {e}", err=True)
