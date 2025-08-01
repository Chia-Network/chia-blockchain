from __future__ import annotations

from io import TextIOWrapper
from typing import Optional

import click

from chia import __version__
from chia.cmds.beta import beta_cmd
from chia.cmds.cmd_classes import ChiaCliContext
from chia.cmds.completion import completion
from chia.cmds.configure import configure_cmd
from chia.cmds.data import data_cmd
from chia.cmds.db import db_cmd
from chia.cmds.dev.main import dev_cmd
from chia.cmds.farm import farm_cmd
from chia.cmds.init import init_cmd
from chia.cmds.keys import keys_cmd
from chia.cmds.netspace import netspace_cmd
from chia.cmds.passphrase import passphrase_cmd
from chia.cmds.peer import peer_cmd
from chia.cmds.plotnft import plotnft_cmd
from chia.cmds.plots import plots_cmd
from chia.cmds.plotters import plotters_cmd
from chia.cmds.rpc import rpc_cmd
from chia.cmds.show import show_cmd
from chia.cmds.start import start_cmd
from chia.cmds.stop import stop_cmd
from chia.cmds.wallet import wallet_cmd
from chia.ssl.ssl_check import check_ssl
from chia.util.default_root import DEFAULT_KEYS_ROOT_PATH, resolve_root_path
from chia.util.errors import KeychainCurrentPassphraseIsInvalid
from chia.util.keychain import Keychain, set_keys_root_path

CONTEXT_SETTINGS = {
    "help_option_names": ["-h", "--help"],
    "show_default": True,
}


@click.group(
    help=f"\n  Manage chia blockchain infrastructure ({__version__})\n",
    epilog="Try 'chia start node', 'chia netspace -d 192', or 'chia show -s'",
    context_settings=CONTEXT_SETTINGS,
)
@click.option(
    "--root-path",
    default=resolve_root_path(override=None),
    help="Config file root",
    type=click.Path(),
    show_default=True,
)
@click.option(
    "--keys-root-path", default=DEFAULT_KEYS_ROOT_PATH, help="Keyring file root", type=click.Path(), show_default=True
)
@click.option("--passphrase-file", type=click.File("r"), help="File to read the keyring passphrase from")
@click.pass_context
def cli(
    ctx: click.Context,
    root_path: str,
    keys_root_path: str,
    passphrase_file: Optional[TextIOWrapper] = None,
) -> None:
    from pathlib import Path

    context = ChiaCliContext.set_default(ctx=ctx)
    context.root_path = Path(root_path)
    context.keys_root_path = Path(keys_root_path)

    set_keys_root_path(Path(keys_root_path))

    # passphrase_file will be None if the passphrase options have been
    # scrubbed from the CLI options
    if passphrase_file is not None:
        import sys

        from chia.cmds.passphrase_funcs import cache_passphrase, read_passphrase_from_file

        try:
            passphrase = read_passphrase_from_file(passphrase_file)
            if Keychain.master_passphrase_is_valid(passphrase):
                cache_passphrase(passphrase)
            else:
                raise KeychainCurrentPassphraseIsInvalid
        except KeychainCurrentPassphraseIsInvalid:
            if Path(passphrase_file.name).is_file():
                print(f'Invalid passphrase found in "{passphrase_file.name}"')
            else:
                print("Invalid passphrase")
            sys.exit(1)
        except Exception as e:
            print(f"Failed to read passphrase: {e}")

    check_ssl(Path(root_path))


@cli.command("version", help="Show chia version")
def version_cmd() -> None:
    print(__version__)


@cli.command("run_daemon", help="Runs chia daemon")
@click.option(
    "--wait-for-unlock",
    help="If the keyring is passphrase-protected, the daemon will wait for an unlock command before accessing keys",
    default=False,
    is_flag=True,
    hidden=True,  # --wait-for-unlock is only set when launched by chia start <service>
)
@click.pass_context
def run_daemon_cmd(ctx: click.Context, wait_for_unlock: bool) -> None:
    import asyncio

    from chia.daemon.server import async_run_daemon
    from chia.util.keychain import Keychain

    wait_for_unlock = wait_for_unlock and Keychain.is_keyring_locked()

    asyncio.run(async_run_daemon(ChiaCliContext.set_default(ctx).root_path, wait_for_unlock=wait_for_unlock))


cli.add_command(keys_cmd)
cli.add_command(plots_cmd)
cli.add_command(wallet_cmd)
cli.add_command(plotnft_cmd)
cli.add_command(configure_cmd)
cli.add_command(init_cmd)
cli.add_command(rpc_cmd)
cli.add_command(show_cmd)
cli.add_command(start_cmd)
cli.add_command(stop_cmd)
cli.add_command(netspace_cmd)
cli.add_command(farm_cmd)
cli.add_command(plotters_cmd)
cli.add_command(db_cmd)
cli.add_command(peer_cmd)
cli.add_command(data_cmd)
cli.add_command(passphrase_cmd)
cli.add_command(beta_cmd)
cli.add_command(completion)
cli.add_command(dev_cmd)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
