import click


@click.group("keys", short_help="Manage your keys")
@click.pass_context
def keys_cmd(ctx: click.Context):
    """Create, delete, view and use your key pairs"""
    from pathlib import Path

    root_path: Path = ctx.obj["root_path"]
    if not root_path.is_dir():
        raise RuntimeError("Please initialize (or migrate) your config directory with chia init")


@keys_cmd.command("generate", short_help="Generates and adds a key to keychain")
@click.pass_context
def generate_cmd(ctx: click.Context):
    from .init_funcs import check_keys
    from .keys_funcs import generate_and_add

    generate_and_add()
    check_keys(ctx.obj["root_path"])


@keys_cmd.command("show", short_help="Displays all the keys in keychain")
@click.option(
    "--show-mnemonic-seed", help="Show the mnemonic seed of the keys", default=False, show_default=True, is_flag=True
)
def show_cmd(show_mnemonic_seed):
    from .keys_funcs import show_all_keys

    show_all_keys(show_mnemonic_seed)


@keys_cmd.command("add", short_help="Add a private key by mnemonic")
@click.option(
    "--filename",
    "-f",
    default=None,
    help="The filename containing the secret key mnemonic to add",
    type=str,
    required=False,
)
@click.pass_context
def add_cmd(ctx: click.Context, filename: str):
    from .init_funcs import check_keys

    if filename:
        from pathlib import Path
        from .keys_funcs import add_private_key_seed

        mnemonic = Path(filename).read_text().rstrip()
        add_private_key_seed(mnemonic)
    else:
        from .keys_funcs import query_and_add_private_key_seed

        query_and_add_private_key_seed()
    check_keys(ctx.obj["root_path"])


@keys_cmd.command("delete", short_help="Delete a key by its pk fingerprint in hex form")
@click.option(
    "--fingerprint",
    "-f",
    default=None,
    help="Enter the fingerprint of the key you want to use",
    type=int,
    required=True,
)
@click.pass_context
def delete_cmd(ctx: click.Context, fingerprint: int):
    from .init_funcs import check_keys
    from .keys_funcs import delete

    delete(fingerprint)
    check_keys(ctx.obj["root_path"])


@keys_cmd.command("delete_all", short_help="Delete all private keys in keychain")
def delete_all_cmd():
    from .keys_funcs import keychain

    keychain.delete_all_keys()


@keys_cmd.command("generate_and_print", short_help="Generates but does NOT add to keychain")
def generate_and_print_cmd():
    from .keys_funcs import generate_and_print

    generate_and_print()


@keys_cmd.command("sign", short_help="Sign a message with a private key")
@click.option("--message", "-d", default=None, help="Enter the message to sign in UTF-8", type=str, required=True)
@click.option(
    "--fingerprint",
    "-f",
    default=None,
    help="Enter the fingerprint of the key you want to use",
    type=int,
    required=True,
)
@click.option("--hd_path", "-t", help="Enter the HD path in the form 'm/12381/8444/n/n'", type=str, required=True)
def sign_cmd(message: str, fingerprint: int, hd_path: str):
    from .keys_funcs import sign

    sign(message, fingerprint, hd_path)


@keys_cmd.command("verify", short_help="Verify a signature with a pk")
@click.option("--message", "-d", default=None, help="Enter the message to sign in UTF-8", type=str, required=True)
@click.option("--public_key", "-p", default=None, help="Enter the pk in hex", type=str, required=True)
@click.option("--signature", "-s", default=None, help="Enter the signature in hex", type=str, required=True)
def verify_cmd(message: str, public_key: str, signature: str):
    from .keys_funcs import verify

    verify(message, public_key, signature)
