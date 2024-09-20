from __future__ import annotations

from typing import Optional, Tuple

import click
from chia_rs import PrivateKey

from chia.cmds import options


@click.group("keys", help="Manage your keys")
@click.pass_context
def keys_cmd(ctx: click.Context) -> None:
    """Create, delete, view and use your key pairs"""
    from pathlib import Path

    root_path: Path = ctx.obj["root_path"]
    if not root_path.is_dir():
        raise RuntimeError("Please initialize (or migrate) your config directory with chia init")


@keys_cmd.command("generate", help="Generates and adds a key to keychain")
@click.option(
    "--label",
    "-l",
    default=None,
    help="Enter the label for the key",
    type=str,
    required=False,
)
@click.pass_context
def generate_cmd(ctx: click.Context, label: Optional[str]) -> None:
    from .init_funcs import check_keys
    from .keys_funcs import generate_and_add

    generate_and_add(label)
    check_keys(ctx.obj["root_path"])


@keys_cmd.command("show", help="Displays all the keys in keychain or the key with the given fingerprint")
@click.option(
    "--show-mnemonic-seed", help="Show the mnemonic seed of the keys", default=False, show_default=True, is_flag=True
)
@click.option(
    "--non-observer-derivation",
    "-d",
    help=(
        "Show the first wallet address using non-observer derivation. Older Chia versions use "
        "non-observer derivation when generating wallet addresses."
    ),
    default=False,
    show_default=True,
    is_flag=True,
)
@click.option(
    "--json",
    "-j",
    help=("Displays all the keys in keychain as JSON"),
    default=False,
    show_default=True,
    is_flag=True,
)
@click.option(
    "--bech32m-prefix",
    help=("Encode public keys in bech32m with a specified prefix"),
    default=None,
)
@options.create_fingerprint()
@click.pass_context
def show_cmd(
    ctx: click.Context,
    show_mnemonic_seed: bool,
    non_observer_derivation: bool,
    json: bool,
    fingerprint: Optional[int],
    bech32m_prefix: Optional[str],
) -> None:
    from .keys_funcs import show_keys

    show_keys(ctx.obj["root_path"], show_mnemonic_seed, non_observer_derivation, json, fingerprint, bech32m_prefix)


@keys_cmd.command("add", help="Add a private key by mnemonic or public key as hex")
@click.option(
    "--filename",
    "-f",
    default=None,
    help="The filename containing the secret key mnemonic or public key hex to add",
    type=str,
    required=False,
)
@click.option(
    "--label",
    "-l",
    default=None,
    help="Enter the label for the key",
    type=str,
    required=False,
)
@click.pass_context
def add_cmd(ctx: click.Context, filename: str, label: Optional[str]) -> None:
    from .init_funcs import check_keys
    from .keys_funcs import query_and_add_key_info

    mnemonic_or_pk = None
    if filename:
        from pathlib import Path

        mnemonic_or_pk = Path(filename).read_text().rstrip()

    query_and_add_key_info(mnemonic_or_pk, label)
    check_keys(ctx.obj["root_path"])


@keys_cmd.group("label", help="Manage your key labels")
def label_cmd() -> None:
    pass


@label_cmd.command("show", help="Show the labels of all available keys")
def show_label_cmd() -> None:
    from .keys_funcs import show_all_key_labels

    show_all_key_labels()


@label_cmd.command("set", help="Set the label of a key")
@options.create_fingerprint(required=True)
@click.option(
    "--label",
    "-l",
    help="Enter the new label for the key",
    type=str,
    required=True,
)
def set_label_cmd(fingerprint: int, label: str) -> None:
    from .keys_funcs import set_key_label

    set_key_label(fingerprint, label)


@label_cmd.command("delete", help="Delete the label of a key")
@options.create_fingerprint(required=True)
def delete_label_cmd(fingerprint: int) -> None:
    from .keys_funcs import delete_key_label

    delete_key_label(fingerprint)


@keys_cmd.command("delete", help="Delete a key by its pk fingerprint in hex form")
@options.create_fingerprint(required=True)
@click.pass_context
def delete_cmd(ctx: click.Context, fingerprint: int) -> None:
    from .init_funcs import check_keys
    from .keys_funcs import delete

    delete(fingerprint)
    check_keys(ctx.obj["root_path"])


@keys_cmd.command("delete_all", help="Delete all private keys in keychain")
def delete_all_cmd() -> None:
    from chia.util.keychain import Keychain

    Keychain().delete_all_keys()


@keys_cmd.command("generate_and_print", help="Generates but does NOT add to keychain")
def generate_and_print_cmd() -> None:
    from .keys_funcs import generate_and_print

    generate_and_print()


@keys_cmd.command("sign", help="Sign a message with a private key")
@click.option("--message", "-d", default=None, help="Enter the message to sign in UTF-8", type=str, required=True)
@options.create_fingerprint()
@click.option(
    "--mnemonic-seed-filename",
    "filename",  # Rename the target argument
    default=None,
    help="The filename containing the mnemonic seed of the master key used for signing.",
    type=str,
    required=False,
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
@click.option(
    "--json",
    "-j",
    help=("Write the signature output in JSON format"),
    default=False,
    show_default=True,
    is_flag=True,
)
def sign_cmd(
    message: str, fingerprint: Optional[int], filename: Optional[str], hd_path: str, as_bytes: bool, json: bool
) -> None:
    from .keys_funcs import resolve_derivation_master_key, sign

    _, resolved_sk = resolve_derivation_master_key(filename if filename is not None else fingerprint)

    if resolved_sk is None:
        print("Could not resolve a secret key to sign with.")
        return

    sign(message, resolved_sk, hd_path, as_bytes, json)


def parse_signature_json(json_str: str) -> Tuple[str, str, str, str]:
    import json

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        raise click.BadParameter("Invalid JSON string")
    if "message" not in data:
        raise click.BadParameter("Missing 'message' field")
    if "pubkey" not in data:
        raise click.BadParameter("Missing 'pubkey' field")
    if "signature" not in data:
        raise click.BadParameter("Missing 'signature' field")
    if "signing_mode" not in data:
        raise click.BadParameter("Missing 'signing_mode' field")

    return data["message"], data["pubkey"], data["signature"], data["signing_mode"]


@keys_cmd.command("verify", help="Verify a signature with a pk")
@click.option("--message", "-d", default=None, help="Enter the signed message in UTF-8", type=str)
@click.option("--public_key", "-p", default=None, help="Enter the pk in hex", type=str)
@click.option("--signature", "-s", default=None, help="Enter the signature in hex", type=str)
@click.option(
    "--as-bytes",
    "-b",
    help="Verify the signed message as sequence of bytes rather than UTF-8 string. Ignored if --json is used.",
    default=False,
    show_default=True,
    is_flag=True,
)
@click.option(
    "--json",
    "-j",
    help=("Read the signature data from a JSON string. Overrides --message, --public_key, and --signature."),
    show_default=True,
    type=str,
)
def verify_cmd(message: str, public_key: str, signature: str, as_bytes: bool, json: str) -> None:
    from .keys_funcs import as_bytes_from_signing_mode, verify

    if json is not None:
        parsed_message, parsed_pubkey, parsed_sig, parsed_signing_mode_str = parse_signature_json(json)

        verify(parsed_message, parsed_pubkey, parsed_sig, as_bytes_from_signing_mode(parsed_signing_mode_str))
    else:
        verify(message, public_key, signature, as_bytes)


@keys_cmd.group("derive", help="Derive child keys or wallet addresses")
@options.create_fingerprint()
@click.option(
    "--mnemonic-seed-filename",
    "filename",  # Rename the target argument
    default=None,
    help="The filename containing the mnemonic seed of the master key to derive from.",
    type=str,
    required=False,
)
@click.pass_context
def derive_cmd(ctx: click.Context, fingerprint: Optional[int], filename: Optional[str]) -> None:
    ctx.obj["fingerprint"] = fingerprint
    ctx.obj["filename"] = filename


@derive_cmd.command("search", help="Search the keyring for one or more matching derived keys or wallet addresses")
@click.argument("search-terms", type=str, nargs=-1)
@click.option(
    "--limit", "-l", default=100, show_default=True, help="Limit the number of derivations to search against", type=int
)
@click.option(
    "--non-observer-derivation",
    "-d",
    help="Search will be performed against keys derived using non-observer derivation.",
    default=False,
    show_default=True,
    is_flag=True,
)
@click.option(
    "--show-progress",
    "-P",
    help="Show search progress",
    default=False,
    show_default=True,
    is_flag=True,
)
@click.option(
    "--search-type",
    "-t",
    help="Limit the search to include just the specified types",
    default=["address", "public_key"],
    show_default=True,
    multiple=True,
    type=click.Choice(["public_key", "private_key", "address", "all"], case_sensitive=True),
)
@click.option(
    "--derive-from-hd-path",
    "-p",
    help="Search for items derived from a specific HD path. Indices ending in an 'n' indicate that "
    "non-observer derivation should be used at that index. Example HD path: m/12381n/8444n/2/",
    type=str,
)
@click.option("--prefix", "-x", help="Address prefix (xch for mainnet, txch for testnet)", default=None, type=str)
@click.pass_context
def search_cmd(
    ctx: click.Context,
    search_terms: Tuple[str, ...],
    limit: int,
    non_observer_derivation: bool,
    show_progress: bool,
    search_type: Tuple[str, ...],
    derive_from_hd_path: Optional[str],
    prefix: Optional[str],
) -> None:
    import sys

    from .keys_funcs import resolve_derivation_master_key, search_derive

    fingerprint: Optional[int] = ctx.obj.get("fingerprint", None)
    filename: Optional[str] = ctx.obj.get("filename", None)

    # Specifying the master key is optional for the search command. If not specified, we'll search all keys.
    resolved_sk = None
    if fingerprint is not None or filename is not None:
        _, resolved_sk = resolve_derivation_master_key(filename if filename is not None else fingerprint)
        if resolved_sk is None:
            print("Could not resolve private key from fingerprint/mnemonic file")

    found: bool = search_derive(
        ctx.obj["root_path"],
        fingerprint,
        search_terms,
        limit,
        non_observer_derivation,
        show_progress,
        ("all",) if "all" in search_type else search_type,
        derive_from_hd_path,
        prefix,
        resolved_sk,
    )

    sys.exit(0 if found else 1)


class ResolutionError(Exception):
    pass


def _resolve_fingerprint_and_sk(
    filename: Optional[str], fingerprint: Optional[int], non_observer_derivation: bool
) -> Tuple[Optional[int], Optional[PrivateKey]]:
    from .keys_funcs import resolve_derivation_master_key

    reolved_fp, resolved_sk = resolve_derivation_master_key(filename if filename is not None else fingerprint)

    if non_observer_derivation and resolved_sk is None:
        print("Could not resolve private key for non-observer derivation")
        raise ResolutionError()
    else:
        pass

    if reolved_fp is None:
        print("A fingerprint of a root key to derive from is required")
        raise ResolutionError()

    return reolved_fp, resolved_sk


@derive_cmd.command("wallet-address", help="Derive wallet receive addresses")
@click.option(
    "--index", "-i", help="Index of the first wallet address to derive. Index 0 is the first wallet address.", default=0
)
@click.option("--count", "-n", help="Number of wallet addresses to derive, starting at index.", default=1)
@click.option("--prefix", "-x", help="Address prefix (xch for mainnet, txch for testnet)", default=None, type=str)
@click.option(
    "--non-observer-derivation",
    "-d",
    help="Derive wallet addresses using non-observer derivation.",
    default=False,
    show_default=True,
    is_flag=True,
)
@click.option(
    "--show-hd-path",
    help="Show the HD path of the derived wallet addresses. If non-observer-derivation is specified, "
    "path indices will have an 'n' suffix.",
    default=False,
    show_default=True,
    is_flag=True,
)
@click.pass_context
def wallet_address_cmd(
    ctx: click.Context, index: int, count: int, prefix: Optional[str], non_observer_derivation: bool, show_hd_path: bool
) -> None:
    from .keys_funcs import derive_wallet_address

    fingerprint: Optional[int] = ctx.obj.get("fingerprint", None)
    filename: Optional[str] = ctx.obj.get("filename", None)

    try:
        fingerprint, sk = _resolve_fingerprint_and_sk(filename, fingerprint, non_observer_derivation)
    except ResolutionError:
        return

    derive_wallet_address(
        ctx.obj["root_path"], fingerprint, index, count, prefix, non_observer_derivation, show_hd_path, sk
    )


@derive_cmd.command("child-key", help="Derive child keys")
@click.option(
    "--type",
    "-t",
    "key_type",  # Rename the target argument
    help="Type of child key to derive",
    required=False,
    type=click.Choice(["farmer", "pool", "wallet", "local", "backup", "singleton", "pool_auth"]),
)
@click.option(
    "--derive-from-hd-path",
    "-p",
    help="Derive child keys rooted from a specific HD path. Indices ending in an 'n' indicate that "
    "non-observer derivation should be used at that index. Example HD path: m/12381n/8444n/2/",
    type=str,
)
@click.option(
    "--index", "-i", help="Index of the first child key to derive. Index 0 is the first child key.", default=0
)
@click.option("--count", "-n", help="Number of child keys to derive, starting at index.", default=1)
@click.option(
    "--non-observer-derivation",
    "-d",
    help="Derive keys using non-observer derivation.",
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
@click.option(
    "--bech32m-prefix",
    help=("Encode public keys in bech32m with a specified prefix"),
    default=None,
)
@click.pass_context
def child_key_cmd(
    ctx: click.Context,
    key_type: Optional[str],
    derive_from_hd_path: Optional[str],
    index: int,
    count: int,
    non_observer_derivation: bool,
    show_private_keys: bool,
    show_hd_path: bool,
    bech32m_prefix: Optional[str],
) -> None:
    from .keys_funcs import derive_child_key

    if key_type is None and derive_from_hd_path is None:
        ctx.fail("--type or --derive-from-hd-path is required")

    fingerprint: Optional[int] = ctx.obj.get("fingerprint", None)
    filename: Optional[str] = ctx.obj.get("filename", None)

    try:
        fingerprint, sk = _resolve_fingerprint_and_sk(filename, fingerprint, non_observer_derivation)
    except ResolutionError:
        return

    derive_child_key(
        fingerprint,
        key_type,
        derive_from_hd_path.lower() if derive_from_hd_path is not None else None,
        index,
        count,
        non_observer_derivation,
        show_private_keys,
        show_hd_path,
        sk,
        bech32m_prefix,
    )
