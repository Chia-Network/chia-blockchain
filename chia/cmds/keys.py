import click

from typing import Optional


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
@click.option(
    "--as-bytes",
    "-b",
    help="Sign the message as sequence of bytes rather than UTF-8 string",
    default=False,
    show_default=True,
    is_flag=True,
)
def sign_cmd(message: str, fingerprint: int, hd_path: str, as_bytes: bool):
    from .keys_funcs import sign

    sign(message, fingerprint, hd_path, as_bytes)


@keys_cmd.command("verify", short_help="Verify a signature with a pk")
@click.option("--message", "-d", default=None, help="Enter the message to sign in UTF-8", type=str, required=True)
@click.option("--public_key", "-p", default=None, help="Enter the pk in hex", type=str, required=True)
@click.option("--signature", "-s", default=None, help="Enter the signature in hex", type=str, required=True)
def verify_cmd(message: str, public_key: str, signature: str):
    from .keys_funcs import verify

    verify(message, public_key, signature)


@keys_cmd.group("derive", short_help="Derive child keys or wallet addresses")
@click.option(
    "--fingerprint",
    "-f",
    default=None,
    help="Enter the fingerprint of the key you want to use",
    type=int,
    required=False,
)
@click.option(
    "--mnemonic-seed-filename",
    "filename",  # Rename the target argument
    default=None,
    help="The filename containing the mnemonic seed of the secret key to derive from",
    type=str,
    required=False,
)
@click.pass_context
def derive_cmd(ctx: click.Context, fingerprint: Optional[int], filename: Optional[str]):
    if fingerprint is None and filename is None:
        ctx.fail("Please specify either a fingerprint or a mnemonic seed filename")

    from .keys_funcs import private_key_for_fingerprint

    if fingerprint is not None:
        private_key = private_key_for_fingerprint(fingerprint)
        if private_key is None:
            ctx.fail(f"Fingerprint {fingerprint} not found in keyring")
        else:
            ctx.obj["private_key"] = private_key
    elif filename is not None:
        # TODO: Move into keys_funcs
        from pathlib import Path
        from chia.util.keychain import mnemonic_to_seed
        from blspy import AugSchemeMPL

        mnemonic = Path(filename).read_text().rstrip()
        seed = mnemonic_to_seed(mnemonic, "")
        private_key = AugSchemeMPL.key_gen(seed)
        ctx.obj["private_key"] = private_key


# @derive_cmd.command("search", short_help="Search the keyring for a matching derived key or wallet address")
# @click.argument("search_term", type=str)
# @click.option("--limit", "-l", default=500, help="Limit the number of derivations to search", type=int)
# def search_cmd(search_term: str, limit: int):
#     from .keys_funcs import search_derive

#     search_derive(search_term, limit)


@derive_cmd.command("wallet-address", short_help="Derive wallet receive addresses")
@click.option(
    "--index", "-i", help="Index of the first wallet address to derive. Index 0 is the first wallet address.", default=0
)
@click.option("--count", "-n", help="Number of wallet addresses to derive, starting at index.", default=1)
@click.option("--prefix", "-x", help="Address prefix (xch for mainnet, txch for testnet)", default=None, type=str)
@click.option(
    "--public-derivation",
    "-p",
    help="Derive wallet addresses using public derivation from the master key. Also known as unhardened derivation.",
    default=False,
    show_default=True,
    is_flag=True,
)
@click.option(
    "--show-hd-path",
    help="Show the HD path of the derived wallet addresses",
    default=False,
    show_default=True,
    is_flag=True,
)
@click.pass_context
def wallet_address_cmd(
    ctx: click.Context, index: int, count: int, prefix: Optional[str], public_derivation: bool, show_hd_path: bool
):
    from .keys_funcs import derive_wallet_address

    derive_wallet_address(
        ctx.obj["root_path"], ctx.obj["private_key"], index, count, prefix, public_derivation, show_hd_path
    )


@derive_cmd.command("child-key", short_help="Derive child keys")
@click.option(
    "--type",
    "-t",
    "key_type",  # Rename the target argument
    help="Type of child key to derive",
    required=True,
    type=click.Choice(["farmer", "pool", "wallet", "local", "backup", "singleton", "pool_auth"]),
)
@click.option(
    "--index", "-i", help="Index of the first child key to derive. Index 0 is the first child key.", default=0
)
@click.option("--count", "-n", help="Number of child keys to derive, starting at index.", default=1)
@click.option(
    "--public-derivation",
    "-p",
    help="Derive wallet addresses using public derivation from the master key. Also known as unhardened derivation.",
    default=False,
    show_default=True,
    is_flag=True,
)
@click.option(
    "--show-hd-path",
    help="Show the HD path of the derived wallet addresses",
    default=False,
    show_default=True,
    is_flag=True,
)
@click.pass_context
def child_key_cmd(
    ctx: click.Context, key_type: str, index: int, count: int, public_derivation: bool, show_hd_path: bool
):
    from .keys_funcs import derive_child_key

    derive_child_key(
        ctx.obj["root_path"], ctx.obj["private_key"], key_type, index, count, public_derivation, show_hd_path
    )
