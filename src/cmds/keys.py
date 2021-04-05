from pathlib import Path
from typing import List

import click
from blspy import AugSchemeMPL, G1Element, G2Element

from chia.cmds.init import check_keys
from chia.consensus.coinbase import create_puzzlehash_for_pk
from chia.util.bech32m import encode_puzzle_hash
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.ints import uint32
from chia.util.keychain import Keychain, bytes_to_mnemonic, generate_mnemonic
from chia.wallet.derive_keys import master_sk_to_farmer_sk, master_sk_to_pool_sk, master_sk_to_wallet_sk

keychain: Keychain = Keychain()


def generate_and_print():
    """
    Generates a seed for a private key, and prints the mnemonic to the terminal.
    """

    mnemonic = generate_mnemonic()
    print("Generating private key. Mnemonic (24 secret words):")
    print(mnemonic)
    print('Note that this key has not been added to the keychain. Run chia keys add_seed -m "[MNEMONICS]" to add')
    return mnemonic


def generate_and_add():
    """
    Generates a seed for a private key, prints the mnemonic to the terminal, and adds the key to the keyring.
    """

    mnemonic = generate_mnemonic()
    print("Generating private key")
    add_private_key_seed(mnemonic)


def query_and_add_private_key_seed():
    mnemonic = input("Enter the mnemonic you want to use: ")
    add_private_key_seed(mnemonic)


def add_private_key_seed(mnemonic: str):
    """
    Add a private key seed to the keyring, with the given mnemonic.
    """

    try:
        passphrase = ""
        sk = keychain.add_private_key(mnemonic, passphrase)
        fingerprint = sk.get_g1().get_fingerprint()
        print(f"Added private key with public key fingerprint {fingerprint} and mnemonic")
        print(mnemonic)

    except ValueError as e:
        print(e)
        return


def show_all_keys(show_mnemonic: bool):
    """
    Prints all keys and mnemonics (if available).
    """
    root_path = DEFAULT_ROOT_PATH
    config = load_config(root_path, "config.yaml")
    private_keys = keychain.get_all_private_keys()
    selected = config["selected_network"]
    prefix = config["network_overrides"]["config"][selected]["address_prefix"]
    if len(private_keys) == 0:
        print("There are no saved private keys")
        return
    print("Showing all private keys:")
    for sk, seed in private_keys:
        print("")
        print("Fingerprint:", sk.get_g1().get_fingerprint())
        print("Master public key (m):", sk.get_g1())
        print("Master private key (m):", bytes(sk).hex())
        print(
            "Farmer public key (m/12381/8444/0/0)::",
            master_sk_to_farmer_sk(sk).get_g1(),
        )
        print("Pool public key (m/12381/8444/1/0):", master_sk_to_pool_sk(sk).get_g1())
        print(
            "First wallet key (m/12381/8444/2/0):",
            master_sk_to_wallet_sk(sk, uint32(0)).get_g1(),
        )
        print(
            "First wallet address:",
            encode_puzzle_hash(create_puzzlehash_for_pk(master_sk_to_wallet_sk(sk, uint32(0)).get_g1()), prefix),
        )
        assert seed is not None
        if show_mnemonic:
            mnemonic = bytes_to_mnemonic(seed)
            print("  Mnemonic seed (24 secret words):")
            print(mnemonic)


def delete(fingerprint: int):
    """
    Delete a key by its public key fingerprint (which is an integer).
    """
    print(f"Deleting private_key with fingerprint {fingerprint}")
    keychain.delete_key_by_fingerprint(fingerprint)


def sign(message: str, fingerprint: int, hd_path: str):
    k = Keychain()
    private_keys = k.get_all_private_keys()

    path: List[uint32] = [uint32(int(i)) for i in hd_path.split("/") if i != "m"]
    for sk, _ in private_keys:
        if sk.get_g1().get_fingerprint() == fingerprint:
            for c in path:
                sk = AugSchemeMPL.derive_child_sk(sk, c)
            print("Public key:", sk.get_g1())
            print("Signature:", AugSchemeMPL.sign(sk, bytes(message, "utf-8")))
            return
    print(f"Fingerprint {fingerprint} not found in keychain")


def verify(message: str, public_key: str, signature: str):
    messageBytes = bytes(message, "utf-8")
    public_key = G1Element.from_bytes(bytes.fromhex(public_key))
    signature = G2Element.from_bytes(bytes.fromhex(signature))
    print(AugSchemeMPL.verify(public_key, messageBytes, signature))


@click.group("keys", short_help="Manage your keys")
@click.pass_context
def keys_cmd(ctx: click.Context):
    """Create, delete, view and use your key pairs"""
    root_path: Path = ctx.obj["root_path"]
    if not root_path.is_dir():
        raise RuntimeError("Please initialize (or migrate) your config directory with chia init")


@keys_cmd.command("generate", short_help="Generates and adds a key to keychain")
@click.pass_context
def generate_cmd(ctx: click.Context):
    generate_and_add()
    check_keys(ctx.obj["root_path"])


@keys_cmd.command("show", short_help="Displays all the keys in keychain")
@click.option(
    "--show-mnemonic-seed", help="Show the mnemonic seed of the keys", default=False, show_default=True, is_flag=True
)
def show_cmd(show_mnemonic_seed):
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
    if filename:
        mnemonic = Path(filename).read_text().rstrip()
        add_private_key_seed(mnemonic)
    else:
        query_and_add_private_key_seed()
    check_keys(ctx.obj["root_path"])


@keys_cmd.command("delete", short_help="Delete a key by it's pk fingerprint in hex form")
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
    delete(fingerprint)
    check_keys(ctx.obj["root_path"])


@keys_cmd.command("delete_all", short_help="Delete all private keys in keychain")
def delete_all_cmd():
    keychain.delete_all_keys()


@keys_cmd.command("generate_and_print", short_help="Generates but does NOT add to keychain")
def generate_and_print_cmd():
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
    sign(message, fingerprint, hd_path)


@keys_cmd.command("verify", short_help="Verify a signature with a pk")
@click.option("--message", "-d", default=None, help="Enter the message to sign in UTF-8", type=str, required=True)
@click.option("--public_key", "-p", default=None, help="Enter the pk in hex", type=str, required=True)
@click.option("--signature", "-s", default=None, help="Enter the signature in hex", type=str, required=True)
def verify_cmd(message: str, public_key: str, signature: str):
    verify(message, public_key, signature)
