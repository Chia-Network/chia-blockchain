import click
from chia.cmds.password_funcs import initialize_password, remove_passwords_options_from_cmd, supports_keyring_password


@click.command("init", short_help="Create or migrate the configuration")
@click.option(
    "--create-certs",
    "-c",
    default=None,
    help="Create new SSL certificates based on CA in [directory]",
    type=click.Path(),
)
@click.option(
    "--set-password",
    "-s",
    is_flag=True,
    help="Password protect your keyring"
)
@click.pass_context
def init_cmd(ctx: click.Context, create_certs: str, **kwargs):
    """
    Create a new configuration or migrate from previous versions to current

    \b
    Follow these steps to create new certificates for a remote harvester:
    - Make a copy of your Farming Machine CA directory: ~/.chia/[version]/config/ssl/ca
    - Shut down all chia daemon processes with `chia stop all -d`
    - Run `chia init -c [directory]` on your remote harvester,
      where [directory] is the the copy of your Farming Machine CA directory
    - Get more details on remote harvester on Chia wiki:
      https://github.com/Chia-Network/chia-blockchain/wiki/Farming-on-many-machines
    """
    from pathlib import Path
    from .init_funcs import init

    set_password = kwargs.get("set_password")
    if set_password:
      initialize_password()

    init(Path(create_certs) if create_certs is not None else None, ctx.obj["root_path"])


if not supports_keyring_password():
    # TODO: Remove once keyring password management is rolled out to all platforms
    remove_passwords_options_from_cmd(init_cmd)


if __name__ == "__main__":
    from .init_funcs import chia_init
    from chia.util.default_root import DEFAULT_ROOT_PATH

    chia_init(DEFAULT_ROOT_PATH)
