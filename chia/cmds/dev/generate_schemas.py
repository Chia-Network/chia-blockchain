from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click

import chia
from chia.data_layer.data_layer_api import DataLayerAPI
from chia.farmer.farmer_api import FarmerAPI
from chia.full_node.full_node_api import FullNodeAPI
from chia.harvester.harvester_api import HarvesterAPI
from chia.introducer.introducer_api import IntroducerAPI
from chia.protocols.outbound_message import NodeType
from chia.server.api_protocol import ApiProtocol
from chia.solver.solver_api import SolverAPI
from chia.timelord.timelord_api import TimelordAPI
from chia.wallet.wallet_node_api import WalletNodeAPI


class SchemaGenerationError(Exception):
    """Base exception for schema generation errors."""


class GitTrackingError(SchemaGenerationError):
    """Exception raised when git tracking validation fails."""


class FormattingError(SchemaGenerationError):
    """Exception raised when file formatting fails."""


class RegistryGenerationError(SchemaGenerationError):
    """Exception raised when registry file generation fails."""


# Registry of original implementation APIs for schema generation
source_api_registry: dict[NodeType, type[ApiProtocol]] = {
    NodeType.FULL_NODE: FullNodeAPI,
    NodeType.WALLET: WalletNodeAPI,
    NodeType.INTRODUCER: IntroducerAPI,
    NodeType.TIMELORD: TimelordAPI,
    NodeType.FARMER: FarmerAPI,
    NodeType.HARVESTER: HarvesterAPI,
    NodeType.SOLVER: SolverAPI,
    NodeType.DATA_LAYER: DataLayerAPI,
}

d = set(source_api_registry.keys()).symmetric_difference(NodeType)
if len(d) != 0:
    raise Exception(f"NodeType and source_api_registry out of sync: {d}")

api_class_names: dict[NodeType, str] = {
    **{node_type: node_type.name.title().replace("_", "") for node_type in source_api_registry.keys()},
    NodeType.WALLET: "WalletNode",
    NodeType.FULL_NODE: "FullNode",
}


@click.command("generate-service-peer-schemas")
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(exists=False, path_type=Path),
    # avoiding chia.apis.__file__ directly can help with overwriting broken output files
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
        selected_services = list(source_api_registry.keys())

    generated_files = []
    has_errors = False

    for node_type in selected_services:
        if node_type not in source_api_registry:
            click.echo(f"Warning: No API registered for {node_type.name}", err=True)
            has_errors = True
            continue

        api_class = source_api_registry[node_type]
        output_file = output_dir.joinpath(f"{node_type.name.lower()}_api_schema.py")

        # Generate schema content
        try:
            schema_content = api_class.metadata.create_schema(api_class)

            # Write to file
            with output_file.open("w", encoding="utf-8", newline="\n") as file:
                file.write(schema_content)

            generated_files.append(output_file)
            click.echo(f"Generated {output_file} ({len(schema_content)} characters)")

        except Exception as e:
            click.echo(f"Error generating schema for {node_type.name}: {e}", err=True)
            has_errors = True
            continue

    # Generate ApiProtocolRegistry if requested
    if generate_registry:
        try:
            registry_file = _generate_registry_file(output_dir, selected_services)
            generated_files.append(registry_file)
        except RegistryGenerationError as e:
            click.echo(f"Registry generation failed: {e}", err=True)
            has_errors = True

    try:
        # Verify all generated files are tracked by git
        if generated_files:
            _verify_git_tracking(generated_files)

        # Format generated files if requested
        if format_output and generated_files:
            _format_files(generated_files)

    except (GitTrackingError, FormattingError) as e:
        click.echo(f"Error: {e}", err=True)
        has_errors = True

    if generated_files:
        if has_errors:
            click.echo(f"Generated {len(generated_files)} schema file(s) with errors", err=True)
            sys.exit(1)
        else:
            click.echo(f"Successfully generated {len(generated_files)} schema file(s)")
    else:
        click.echo("No schema files were generated", err=True)
        sys.exit(1)


def _format_files(files: list[Path]) -> None:
    """Format files, raising FormattingError if any errors occurred."""
    formatting_errors = []

    for file_path in files:
        try:
            # Run ruff format
            subprocess.run(
                [sys.executable, "-m", "ruff", "format", file_path], check=True, capture_output=True, text=True
            )
            click.echo(f"  [OK] Formatted {file_path.name}")

        except Exception as e:
            error_msg = f"Failed to format {file_path.name}: {e}"
            click.echo(f"  [FAIL] {error_msg}", err=True)
            formatting_errors.append(error_msg)
            continue

        try:
            # Run ruff check --fix
            subprocess.run(
                [sys.executable, "-m", "ruff", "check", "--fix", file_path],
                check=True,
                capture_output=True,
                text=True,
            )
            click.echo(f"  [OK] No ruff check issues for {file_path.name}")

        except Exception as e:
            error_msg = f"Failed to run ruff check on {file_path.name}: {e}"
            click.echo(f"  [FAIL] {error_msg}", err=True)
            formatting_errors.append(error_msg)

    if formatting_errors:
        raise FormattingError(f"Formatting failed for {len(formatting_errors)} file(s)")


def _verify_git_tracking(files: list[Path]) -> None:
    """Verify all generated files are tracked by git. Raises GitTrackingError if issues found."""
    try:
        # Get list of tracked files from git
        result = subprocess.run(["git", "ls-files"], check=True, capture_output=True, text=True, cwd=Path.cwd())
        tracked_files = set(result.stdout.strip().split("\n"))

        # Check each generated file
        untracked_files = []
        warnings = []

        for file_path in files:
            # Convert to relative path from repo root
            try:
                relative_path = file_path.relative_to(Path.cwd())
                if str(relative_path) not in tracked_files:
                    untracked_files.append(file_path)
            except ValueError:
                # File is outside repo root, can't check tracking
                warning = f"Cannot check git tracking for file outside repo: {file_path}"
                click.echo(f"Warning: {warning}", err=True)
                warnings.append(warning)

        if untracked_files:
            click.echo("ERROR: The following generated files are not tracked by git:", err=True)
            for file_path in untracked_files:
                click.echo(f"  {file_path}", err=True)
            click.echo("Please add these files to git before proceeding.", err=True)
            raise GitTrackingError(f"Found {len(untracked_files)} untracked generated files")
        else:
            click.echo("All generated files are tracked by git")

    except subprocess.CalledProcessError as e:
        error_msg = f"Error checking git status: {e}"
        click.echo(error_msg, err=True)
        raise GitTrackingError(error_msg) from e


def _generate_registry_file(output_dir: Path, selected_services: list[NodeType]) -> Path:
    """Generate the ApiProtocolRegistry __init__.py file. Raises RegistryGenerationError on failure."""
    registry_file = output_dir.joinpath("__init__.py")

    try:
        # Generate imports for each service
        imports = []
        registry_entries = []

        for node_type in sorted(selected_services, key=lambda x: x.name):
            schema_module = f"{node_type.name.lower()}_api_schema"

            # Convert FARMER -> FarmerApiSchema, HARVESTER -> HarvesterApiSchema, etc.
            schema_class = f"{api_class_names[node_type]}ApiSchema"

            imports.append(f"from chia.apis.{schema_module} import {schema_class}")
            registry_entries.append(f"    NodeType.{node_type.name}: {schema_class},")

        joined_imports = "\n".join(imports)
        joined_registry_entries = "\n".join(registry_entries)
        # Generate the complete file content
        content = f"""from __future__ import annotations

{joined_imports}
from chia.protocols.outbound_message import NodeType
from chia.server.api_protocol import ApiSchemaProtocol

ApiProtocolRegistry: dict[NodeType, type[ApiSchemaProtocol]] = {{
{joined_registry_entries}
}}
"""

        with registry_file.open("w", encoding="utf-8", newline="\n") as file:
            file.write(content)

        click.echo(f"Generated {registry_file} ({len(content)} characters)")
        return registry_file

    except Exception as e:
        error_msg = f"Error generating registry file: {e}"
        click.echo(error_msg, err=True)
        raise RegistryGenerationError(error_msg) from e
