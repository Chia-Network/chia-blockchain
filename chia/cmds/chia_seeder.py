import os
from pathlib import Path
from typing import KeysView, Generator

import click
import pkg_resources

from chia import __version__
from chia.cmds.init_funcs import init
from chia.cmds.start import start_cmd
from chia.cmds.stop import stop_cmd
from chia.daemon.server import kill_service, launch_service
from chia.util.config import load_config, save_config
from chia.util.default_root import DEFAULT_ROOT_PATH

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


SERVICES_FOR_GROUP = {
    "all": "chia_seeder_crawler chia_seeder_dns".split(),
    "crawler": "chia_seeder_crawler".split(),
    "dns": "chia_seeder_dns".split(),
}


# TODO: dedupe wrt the eponymous function defined in chia/cmds/chia.py
def monkey_patch_click() -> None:
    # this hacks around what seems to be an incompatibility between the python from `pyinstaller`
    # and `click`
    #
    # Not 100% sure on the details, but it seems that `click` performs a check on start-up
    # that `codecs.lookup(locale.getpreferredencoding()).name != 'ascii'`, and refuses to start
    # if it's not. The python that comes with `pyinstaller` fails this check.
    #
    # This will probably cause problems with the command-line tools that use parameters that
    # are not strict ascii. The real fix is likely with the `pyinstaller` python.

    import click.core

    click.core._verify_python3_env = lambda *args, **kwargs: 0  # type: ignore


def all_groups() -> KeysView[str]:
    return SERVICES_FOR_GROUP.keys()


def services_for_groups(groups) -> Generator[str, None, None]:
    for group in groups:
        for service in SERVICES_FOR_GROUP[group]:
            yield service


def patch_default_chia_dns_config(root_path: Path, filename="config.yaml") -> None:
    """
    Checks if the dns: section exists in the config. If not, the default dns settings are appended to the file
    """

    existing_config = load_config(root_path, "config.yaml")

    if "dns" in existing_config:
        print("DNS section exists in config. No action required.")
        return

    print("DNS section does not exist in config. Patching...")
    config = load_config(root_path, "config.yaml")
    # The following ignores root_path when the second param is absolute, which this will be
    dns_config = load_config(root_path, pkg_resources.resource_filename(__name__, "initial-config.yaml"))

    # Patch in the values with anchors, since pyyaml tends to change
    # the anchors to things like id001, etc
    config["dns"] = dns_config["dns"]
    config["dns"]["network_overrides"] = config["network_overrides"]
    config["dns"]["selected_network"] = config["selected_network"]
    config["dns"]["logging"] = config["logging"]

    # When running as crawler, we default to a much lower client timeout
    config["full_node"]["peer_connect_timeout"] = 2

    save_config(root_path, "config.yaml", config)


def configure(
    root_path: Path,
    testnet: str,
    crawler_db_path: str,
    minimum_version_count: int,
    domain_name: str,
    nameserver: str,
):
    # Run the parent config, in case anythign there (testnet) needs to be run, THEN load the config for local changes
    chia_configure.configure(root_path, None, None, None, None, None, None, None, None, testnet, None)

    config: Dict = load_config(DEFAULT_ROOT_PATH, "config.yaml")
    change_made = False
    if testnet is not None:
        if testnet == "true" or testnet == "t":
            print("Updating Chia DNS to testnet settings")
            port = 58444
            network = "testnet7"
            bootstrap = ["testnet-node.chia.net"]

            config["dns"]["port"] = port
            config["dns"]["other_peers_port"] = port
            config["dns"]["selected_network"] = network
            config["dns"]["bootstrap_peers"] = bootstrap

            change_made = True

        elif testnet == "false" or testnet == "f":
            print("Updating Chia DNS to mainnet settings")
            port = 8444
            network = "mainnet"
            bootstrap = ["node.chia.net"]

            config["dns"]["port"] = port
            config["dns"]["other_peers_port"] = port
            config["dns"]["selected_network"] = network
            config["dns"]["bootstrap_peers"] = bootstrap

            change_made = True
        else:
            print("Please choose True or False")

    if crawler_db_path is not None:
        config["dns"]["crawler_db_path"] = crawler_db_path
        change_made = True

    if minimum_version_count is not None:
        config["dns"]["minimum_version_count"] = minimum_version_count
        change_made = True

    if domain_name is not None:
        config["dns"]["domain_name"] = domain_name
        change_made = True

    if nameserver is not None:
        config["dns"]["nameserver"] = nameserver
        change_made = True

    if change_made:
        print("Restart any running Chia DNS services for changes to take effect")
        save_config(root_path, "config.yaml", config)
    return 0


@click.group(
    help=f"\n  Manage the Chia Seeder ({__version__})\n",
    epilog="Try 'chia_seeder start crawler' or 'chia_seeder start dns'",
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


@click.command("init", short_help="Create or migrate the Chia Seeder configuration")
@click.pass_context
def init_cmd(ctx: click.Context, **kwargs):
    print("Calling Chia Seeder Init...")
    root_path = ctx.obj["root_path"]
    init(None, root_path, True)
    # Standard first run initialization or migration steps. Handles config patching with dns settings
    if os.environ.get("CHIA_ROOT", None) is not None:
        print(f"warning, your CHIA_ROOT is set to {os.environ['CHIA_ROOT']}.")
    print(f"Chia directory {root_path}")
    if root_path.is_dir() and not Path(root_path / "config" / "config.yaml").exists():
        # This is reached if CHIA_ROOT is set, but there is no config
        # This really shouldn't happen, but if we dont have the base chia config, we can't continue
        print("Config does not exist. Can't continue!")
        return -1
    patch_default_chia_dns_config(root_path)
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
