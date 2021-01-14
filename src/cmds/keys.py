from pathlib import Path
from typing import List

from blspy import AugSchemeMPL, G1Element, G2Element

from src.cmds.init import check_keys
from src.util.bech32m import encode_puzzle_hash
from src.util.keychain import (
    generate_mnemonic,
    bytes_to_mnemonic,
    Keychain,
)
from src.wallet.derive_keys import (
    master_sk_to_pool_sk,
    master_sk_to_farmer_sk,
    master_sk_to_wallet_sk,
)
from src.util.ints import uint32
from src.consensus.coinbase import create_puzzlehash_for_pk

command_list = [
    "generate",
    "generate_and_print",
    "show",
    "add",
    "delete",
    "delete_all",
    "sign",
    "verify",
]


def help_message():
    print("usage: chia keys command")
    print(f"command can be any of {command_list}")
    print("")
    print("chia keys generate  (generates and adds a key to keychain)")
    print("chia keys generate_and_print  (generates but does NOT add to keychain)")
    print("chia keys show (displays all the keys in keychain)")
    print("chia keys add -m [24 words] (add a private key through the mnemonic)")
    print("chia keys delete -f [fingerprint] (delete a key by it's pk fingerprint in hex form)")
    print("chia keys delete_all (delete all private keys in keychain)")
    print("chia keys sign -f [fingerprint] -t [hd_path] -d [message] (sign a message with a private key)")
    print("chia keys verify -p [public_key] -d [message] -s [signature] (verify a signature with a pk)")


def make_parser(parser):
    parser.add_argument(
        "-m",
        "--mnemonic",
        type=str,
        nargs=24,
        default=None,
        help="Enter mnemonic you want to use",
    )
    parser.add_argument(
        "-k",
        "--key",
        type=str,
        default=None,
        help="Enter the raw private key in hex",
    )
    parser.add_argument(
        "-f",
        "--fingerprint",
        type=int,
        default=None,
        help="Enter the fingerprint of the key you want to use",
    )

    parser.add_argument(
        "-t",
        "--hd_path",
        type=str,
        default=None,
        help="Enter the HD path in the form 'm/12381/8444/n/n'",
    )

    parser.add_argument(
        "-d",
        "--message",
        type=str,
        default=None,
        help="Enter the message to sign in UTF-8",
    )

    parser.add_argument(
        "-p",
        "--public_key",
        type=str,
        default=None,
        help="Enter the pk in hex",
    )

    parser.add_argument(
        "-s",
        "--signature",
        type=str,
        default=None,
        help="Enter the signature in hex",
    )

    parser.add_argument(
        "command",
        help=f"Command can be any one of {command_list}",
        type=str,
        nargs="?",
    )
    parser.set_defaults(function=handler)
    parser.print_help = lambda self=parser: help_message()


keychain: Keychain = Keychain()


def generate_and_print():
    """
    Generates a seed for a private key, and prints the mnemonic to the terminal.
    """

    mnemonic = generate_mnemonic()
    print("Generating private key. Mnemonic (24 secret words):")
    print(mnemonic)
    print("Note that this key has not been added to the keychain. Run chia keys add_seed -m [MNEMONICS] to add")
    return mnemonic


def generate_and_add():
    """
    Generates a seed for a private key, prints the mnemonic to the terminal, and adds the key to the keyring.
    """

    mnemonic = generate_mnemonic()
    print("Generating private key.")
    add_private_key_seed(mnemonic)


def add_private_key_seed(mnemonic):
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


def show_all_keys():
    """
    Prints all keys and mnemonics (if available).
    """

    private_keys = keychain.get_all_private_keys()
    if len(private_keys) == 0:
        print("There are no saved private keys.")
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
            encode_puzzle_hash(create_puzzlehash_for_pk(master_sk_to_wallet_sk(sk, uint32(0)).get_g1())),
        )
        assert seed is not None
        mnemonic = bytes_to_mnemonic(seed)
        print("  Mnemonic seed (24 secret words):")
        print(mnemonic)


def delete(args):
    """
    Delete a key by it's public key fingerprint (which is an int).
    """
    if args.fingerprint is None:
        print("Please specify the fingerprint argument -f")
        quit()

    fingerprint = args.fingerprint
    assert fingerprint is not None
    print(f"Deleting private_key with fingerprint {fingerprint}")
    keychain.delete_key_by_fingerprint(fingerprint)


def sign(args):
    if args.message is None:
        print("Please specify the message argument -d")
        quit()

    if args.fingerprint is None or args.hd_path is None:
        print("Please specify the fingerprint argument -f and hd_path argument -t")
        quit()

    message = args.message
    assert message is not None

    k = Keychain()
    private_keys = k.get_all_private_keys()

    fingerprint = args.fingerprint
    assert fingerprint is not None
    hd_path = args.hd_path
    assert hd_path is not None
    path: List[uint32] = [uint32(int(i)) for i in hd_path.split("/") if i != "m"]
    for sk, _ in private_keys:
        if sk.get_g1().get_fingerprint() == fingerprint:
            for c in path:
                sk = AugSchemeMPL.derive_child_sk(sk, c)
            print("Public key:", sk.get_g1())
            print("Signature:", AugSchemeMPL.sign(sk, bytes(message, "utf-8")))
            return
    print(f"Fingerprint {fingerprint} not found in keychain")


def verify(args):
    if args.message is None:
        print("Please specify the message argument -d")
        quit()
    if args.public_key is None:
        print("Please specify the public_key argument -p")
        quit()
    if args.signature is None:
        print("Please specify the signature argument -s")
        quit()
    assert args.message is not None
    assert args.public_key is not None
    assert args.signature is not None
    message = bytes(args.message, "utf-8")
    public_key = G1Element.from_bytes(bytes.fromhex(args.public_key))
    signature = G2Element.from_bytes(bytes.fromhex(args.signature))
    print(AugSchemeMPL.verify(public_key, message, signature))


def handler(args, parser):
    if args.command is None or len(args.command) < 1:
        help_message()
        parser.exit(1)

    root_path: Path = args.root_path
    if not root_path.is_dir():
        raise RuntimeError("Please initialize (or migrate) your config directory with chia init.")

    command = args.command
    if command not in command_list:
        help_message()
        parser.exit(1)

    if command == "generate":
        generate_and_add()
        check_keys(root_path)
    elif command == "show":
        show_all_keys()
    elif command == "add":
        add_private_key_seed(" ".join(args.mnemonic))
        check_keys(root_path)
    elif command == "delete":
        delete(args)
        check_keys(root_path)
    elif command == "delete_all":
        keychain.delete_all_keys()
    if command == "generate_and_print":
        generate_and_print()
    if command == "sign":
        sign(args)
    if command == "verify":
        verify(args)
