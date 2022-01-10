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
    help="Enter the fingerprint of the key you want to use.",
    type=int,
    required=False,
)
@click.option(
    "--mnemonic-seed-filename",
    "filename",  # Rename the target argument
    default=None,
    help="The filename containing the mnemonic seed of the secret key to derive from.",
    type=str,
    required=False,
)
@click.pass_context
def derive_cmd(ctx: click.Context, fingerprint: Optional[int], filename: Optional[str]):
    ctx.obj["fingerprint"] = fingerprint
    ctx.obj["filename"] = filename


@derive_cmd.command("search", short_help="Search the keyring for a matching derived key or wallet address")
@click.argument("search-term", type=str)
@click.option("--limit", "-l", default=500, help="Limit the number of derivations to search against", type=int)
@click.option(
    "--hardened-derivation",
    "-d",
    help="Search against keys derived using hardened derivation.",
    default=False,
    show_default=True,
    is_flag=True,
)
@click.option(
    "--no-progress",
    "-P",
    help="Do not show search progress",
    default=False,
    show_default=True,
    is_flag=True,
)
@click.pass_context
def search_cmd(
    ctx: click.Context, search_term: str, limit: int, hardened_derivation: bool, no_progress: bool
):
    import sys
    from .keys_funcs import search_derive, resolve_derivation_master_key
    from blspy import PrivateKey

    private_key: Optional[PrivateKey] = None
    fingerprint: Optional[int] = ctx.obj.get("fingerprint", None)
    filename: Optional[str] = ctx.obj.get("filename", None)

    # Specifying the master key is optional for the search command. If not specified, we'll search all keys.
    if fingerprint is not None or filename is not None:
        private_key = resolve_derivation_master_key(ctx.obj["fingerprint"], ctx.obj["filename"])

    found: bool = search_derive(ctx.obj["root_path"], private_key, search_term, limit, hardened_derivation, no_progress)

    sys.exit(0 if found else 1)


@derive_cmd.command("wallet-address", short_help="Derive wallet receive addresses")
@click.option(
    "--index", "-i", help="Index of the first wallet address to derive. Index 0 is the first wallet address.", default=0
)
@click.option("--count", "-n", help="Number of wallet addresses to derive, starting at index.", default=1)
@click.option("--prefix", "-x", help="Address prefix (xch for mainnet, txch for testnet)", default=None, type=str)
@click.option(
    "--hardened-derivation",
    "-d",
    help="Derive wallet addresses using hardened derivation.",
    default=False,
    show_default=True,
    is_flag=True,
)
@click.option(
    "--show-hd-path",
    help="Show the HD path of the derived wallet addresses. If hardened-derivation is specified, "
    "path indices will have an 'h' suffix.",
    default=False,
    show_default=True,
    is_flag=True,
)
@click.pass_context
def wallet_address_cmd(
    ctx: click.Context, index: int, count: int, prefix: Optional[str], hardened_derivation: bool, show_hd_path: bool
):
    from .keys_funcs import derive_wallet_address, resolve_derivation_master_key

    private_key = resolve_derivation_master_key(ctx.obj["fingerprint"], ctx.obj["filename"])

    derive_wallet_address(ctx.obj["root_path"], private_key, index, count, prefix, hardened_derivation, show_hd_path)


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
    "--hardened-derivation",
    "-p",
    help="Derive keys using hardened derivation.",
    default=False,
    show_default=True,
    is_flag=True,
)
@click.option(
    "--show-private-keys",
    "-s",
    help="Display derived private keys",
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
    ctx: click.Context,
    key_type: str,
    index: int,
    count: int,
    hardened_derivation: bool,
    show_private_keys: bool,
    show_hd_path: bool,
):
    from .keys_funcs import derive_child_key, resolve_derivation_master_key

    private_key = resolve_derivation_master_key(ctx.obj["fingerprint"], ctx.obj["filename"])

    derive_child_key(
        ctx.obj["root_path"],
        private_key,
        key_type,
        index,
        count,
        hardened_derivation,
        show_private_keys,
        show_hd_path,
    )
