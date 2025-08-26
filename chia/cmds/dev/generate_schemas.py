from __future__ import annotations

import io
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import click

import chia

# import chia.apis
from chia.farmer.farmer_api import FarmerAPI
from chia.full_node.full_node_api import FullNodeAPI
from chia.harvester.harvester_api import HarvesterAPI
from chia.introducer.introducer_api import IntroducerAPI
from chia.protocols.outbound_message import NodeType
from chia.server.api_protocol import ApiProtocol
from chia.solver.solver_api import SolverAPI
from chia.timelord.timelord_api import TimelordAPI
from chia.wallet.wallet_node_api import WalletNodeAPI

# Registry of original implementation APIs for schema generation
SourceApiRegistry: dict[NodeType, type[ApiProtocol]] = {
    NodeType.FULL_NODE: FullNodeAPI,
    NodeType.WALLET: WalletNodeAPI,
    NodeType.INTRODUCER: IntroducerAPI,
    NodeType.TIMELORD: TimelordAPI,
    NodeType.FARMER: FarmerAPI,
    NodeType.HARVESTER: HarvesterAPI,
    NodeType.SOLVER: SolverAPI,
}


@click.command("generate-service-peer-schemas")
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(exists=False, path_type=Path),
    # default=Path(chia.apis.__file__).parent,
    default=Path(chia.__file__).parent.joinpath("apis"),
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
@click.option(
    "--generate-registry/--no-registry",
    default=True,
    help="Generate ApiProtocolRegistry file",
)
def generate_service_peer_schemas_cmd(
    output_dir: Path,
    service: tuple[str, ...],
    format_output: bool,
    generate_registry: bool,
) -> None:
    """Generate service peer API schemas from registered API protocols."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Determine which services to generate
    if service:
        selected_services = [NodeType[name.upper()] for name in service]
    else:
        selected_services = list(SourceApiRegistry.keys())

    generated_files = []

    for node_type in selected_services:
        if node_type not in SourceApiRegistry:
            click.echo(f"Warning: No API registered for {node_type.name}", err=True)
            continue

        api_class = SourceApiRegistry[node_type]
        output_file = output_dir / f"{node_type.name.lower()}_api_schema.py"

        # Generate schema content
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                api_class.metadata.create_schema(api_class)

            schema_content = output.getvalue()

            # Write to file
            with open(output_file, "w", encoding="utf-8", newline="\n") as f:
                f.write(schema_content)

            generated_files.append(output_file)
            click.echo(f"Generated {output_file} ({len(schema_content)} characters)")

        except Exception as e:
            click.echo(f"Error generating schema for {node_type.name}: {e}", err=True)
            continue

    # Generate ApiProtocolRegistry if requested
    if generate_registry:
        registry_file = _generate_registry_file(output_dir, selected_services)
        if registry_file:
            generated_files.append(registry_file)

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
                click.echo(f"  [OK] Formatted {file_path.name}")
            else:
                click.echo(f"  [FAIL] ruff format failed for {file_path.name}: {result.stderr}", err=True)

        except Exception as e:
            click.echo(f"  [FAIL] Failed to format {file_path.name}: {e}", err=True)
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
                click.echo(f"  [OK] No ruff check issues for {file_path.name}")
            else:
                click.echo(f"  [OK] Fixed ruff check issues for {file_path.name}")

        except Exception as e:
            click.echo(f"  [FAIL] Failed to run ruff check on {file_path.name}: {e}", err=True)


def _generate_registry_file(output_dir: Path, selected_services: list[NodeType]) -> Path | None:
    """Generate the ApiProtocolRegistry __init__.py file."""
    registry_file = output_dir / "__init__.py"

    try:
        # Generate imports for each service
        imports = []
        registry_entries = []

        for node_type in sorted(selected_services, key=lambda x: x.name):
            schema_module = f"{node_type.name.lower()}_api_schema"

            # Handle special cases for class names
            if node_type == NodeType.WALLET:
                schema_class = "WalletNodeApiSchema"
            elif node_type == NodeType.FULL_NODE:
                schema_class = "FullNodeApiSchema"
            else:
                # Convert FARMER -> FarmerApiSchema, HARVESTER -> HarvesterApiSchema, etc.
                schema_class = f"{node_type.name.title()}ApiSchema"

            imports.append(f"from chia.apis.{schema_module} import {schema_class}")
            registry_entries.append(f"    NodeType.{node_type.name}: {schema_class},")

        # Generate the complete file content
        content = f"""from __future__ import annotations

{chr(10).join(imports)}
from chia.protocols.outbound_message import NodeType
from chia.server.api_protocol import ApiProtocolSchema

ApiProtocolRegistry: dict[NodeType, type[ApiProtocolSchema]] = {{
{chr(10).join(registry_entries)}
}}
"""

        # Write to file
        with open(registry_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)

        click.echo(f"Generated {registry_file} ({len(content)} characters)")
        return registry_file

    except Exception as e:
        click.echo(f"Error generating registry file: {e}", err=True)
        return None
