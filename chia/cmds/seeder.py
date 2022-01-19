import os
from pathlib import Path
from typing import Dict

import click

import chia.cmds.configure as chia_configure
from chia import __version__
from chia.cmds.chia import monkey_patch_click
from chia.cmds.init_funcs import init
from chia.seeder.util.config import patch_default_seeder_config
from chia.seeder.util.service_groups import all_groups, services_for_groups
from chia.seeder.util.service import launch_service, kill_service
from chia.util.config import load_config, save_config
from chia.util.default_root import DEFAULT_ROOT_PATH

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.group(
    help=f"\n  Manage the Chia Seeder ({__version__})\n",
    epilog="Try 'chia seeder start crawler' or 'chia seeder start server'",
    context_settings=CONTEXT_SETTINGS,
)
@click.option("--root-path", default=DEFAULT_ROOT_PATH, help="Config file root", type=click.Path(), show_default=True)
@click.pass_context
def cli(
    ctx: click.Context,
    root_path: str,
) -> None:
    from pathlib import Path

    ctx.ensure_object(dict)
    ctx.obj["root_path"] = Path(root_path)


@cli.command("version", short_help="Show the Chia Seeder version")
def version_cmd() -> None:
    print(__version__)


@click.command("init", short_help="Create or migrate the configuration")
@click.pass_context
def init_cmd(ctx: click.Context, **kwargs):
    print("Calling Chia Seeder Init...")
    init(None, ctx.obj["root_path"], True)
    if os.environ.get("CHIA_ROOT", None) is not None:
        print(f"warning, your CHIA_ROOT is set to {os.environ['CHIA_ROOT']}.")
    root_path = ctx.obj["root_path"]
    print(f"Chia directory {root_path}")
    if root_path.is_dir() and not Path(root_path / "config" / "config.yaml").exists():
        # This is reached if CHIA_ROOT is set, but there is no config
        # This really shouldn't happen, but if we dont have the base chia config, we can't continue
        print("Config does not exist. Can't continue!")
        return -1
    patch_default_seeder_config(root_path)
    return 0


@click.command("start", short_help="Start service groups")
@click.argument("group", type=click.Choice(all_groups()), nargs=-1, required=True)
@click.pass_context
def start_cmd(ctx: click.Context, group: str) -> None:
    services = services_for_groups(group)

    for service in services:
        print(f"Starting {service}")
        launch_service(ctx.obj["root_path"], service)


@click.command("stop", short_help="Stop service groups")
@click.argument("group", type=click.Choice(all_groups()), nargs=-1, required=True)
@click.pass_context
def stop_cmd(ctx: click.Context, group: str) -> None:
    services = services_for_groups(group)

    for service in services:
        print(f"Stopping {service}")
        kill_service(ctx.obj["root_path"], service)


def configure(
    root_path: Path,
    testnet: str,
    crawler_db_path: str,
    minimum_version_count: int,
    domain_name: str,
    nameserver: str,
):
    # Run the parent config, in case anything there (testnet) needs to be run, THEN load the config for local changes
    chia_configure.configure(root_path, "", "", "", "", "", "", "", "", testnet, "")

    config: Dict = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    change_made = False
    if testnet is not None:
        if testnet == "true" or testnet == "t":
            print("Updating Chia Seeder to testnet settings")
            port = 58444
            network = "testnet10"
            bootstrap = ["testnet-node.chia.net"]

            config["seeder"]["port"] = port
            config["seeder"]["other_peers_port"] = port
            config["seeder"]["selected_network"] = network
            config["seeder"]["bootstrap_peers"] = bootstrap

            change_made = True

        elif testnet == "false" or testnet == "f":
            print("Updating Chia Seeder to mainnet settings")
            port = 8444
            network = "mainnet"
            bootstrap = ["node.chia.net"]

            config["seeder"]["port"] = port
            config["seeder"]["other_peers_port"] = port
            config["seeder"]["selected_network"] = network
            config["seeder"]["bootstrap_peers"] = bootstrap

            change_made = True
        else:
            print("Please choose True or False")

    if crawler_db_path is not None:
        config["seeder"]["crawler_db_path"] = crawler_db_path
        change_made = True

    if minimum_version_count is not None:
        config["seeder"]["minimum_version_count"] = minimum_version_count
        change_made = True

    if domain_name is not None:
        config["seeder"]["domain_name"] = domain_name
        change_made = True

    if nameserver is not None:
        config["seeder"]["nameserver"] = nameserver
        change_made = True

    if change_made:
        print("Restart any running Chia Seeder services for changes to take effect")
        save_config(root_path, "config.yaml", config)
    return 0


@click.command("configure", short_help="Modify configuration")
@click.option(
    "--testnet",
    "-t",
    help="configures for connection to testnet",
    type=click.Choice(["true", "t", "false", "f"]),
)
@click.option(
    "--crawler-db-path",
    help="configures for path to the crawler database",
    type=str,
)
@click.option(
    "--minimum-version-count",
    help="configures how many of a particular version must be seen to be reported in logs",
    type=int,
)
@click.option(
    "--domain-name",
    help="configures the domain_name setting. Ex: `seeder.example.com.`",
    type=str,
)
@click.option(
    "--nameserver",
    help="configures the nameserver setting. Ex: `example.com.`",
    type=str,
)
@click.pass_context
def configure_cmd(
    ctx,
    testnet,
    crawler_db_path,
    minimum_version_count,
    domain_name,
    nameserver,
):
    configure(
        ctx.obj["root_path"],
        testnet,
        crawler_db_path,
        minimum_version_count,
        domain_name,
        nameserver,
    )


cli.add_command(init_cmd)
cli.add_command(start_cmd)
cli.add_command(stop_cmd)
cli.add_command(configure_cmd)


def main() -> None:
    monkey_patch_click()
    cli()  # pylint: disable=no-value-for-parameter


if __name__ == "__main__":
    main()
