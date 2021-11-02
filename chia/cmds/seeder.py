import os
from pathlib import Path

import click
import pkg_resources

from chia import __version__
from chia.cmds.init_funcs import init
from chia.cmds.start import start_cmd
from chia.cmds.stop import stop_cmd
from chia.cmds.configure import configure_cmd
from chia.util.config import load_config, save_config
from chia.util.default_root import DEFAULT_ROOT_PATH

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])

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


def patch_default_chiadns_config(root_path: Path, filename="config.yaml") -> None:
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


@click.group(
    help=f"\n  Manage the Chia Seeder ({__version__})\n",
    epilog="Try 'seeder start crawler' or 'seeder start dns'",
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


@cli.command("version", short_help="Show Chia Seeder version")
def version_cmd() -> None:
    print(__version__)


@click.command("init", short_help="Create or migrate the Chia Seeder configuration")
@click.pass_context
def init_cmd(ctx: click.Context, **kwargs):
    print("Calling Chia Seder Init...")
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
    patch_default_chiadns_config(root_path)
    return 0


cli.add_command(init_cmd)
cli.add_command(start_cmd)
cli.add_command(stop_cmd)
cli.add_command(configure_cmd)


def main() -> None:
    monkey_patch_click()
    cli()  # pylint: disable=no-value-for-parameter


if __name__ == "__main__":
    main()
