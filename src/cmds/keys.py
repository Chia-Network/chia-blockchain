from pathlib import Path
from src.cmds.init import check_keys
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
]


def help_message():
    print("usage: chia keys command")
    print(f"command can be any of {command_list}")
    print("")
    print("chia keys generate  (generates and adds a key to keychain)")
    print("chia keys generate_and_print  (generates but does NOT add to keychain)")
    print("chia keys show (displays all the keys in keychain)")
    print("chia keys add -m [24 words] (add a private key through the mnemonic)")
    print(
        "chia keys delete -f [fingerprint] (delete a key by it's pk fingerprint in hex form)"
    )
    print("chia keys delete_all (delete all private keys in keychain)")


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
        "-k", "--key", type=str, default=None, help="Enter the raw private key in hex",
    )
    parser.add_argument(
        "-f",
        "--fingerprint",
        type=int,
        default=None,
        help="Enter the fingerprint of the key you want to delete",
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
    mnemonics_string = mnemonic_to_string(mnemonic)
    print("Generating private key. Mnemonic:")
    print(mnemonics_string)
    print(
        "Note that this key has not been added to the keychain. Run chia keys add_seed -m [MNEMONICS] to add"
    )
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
        print(
            f"Added private key with public key fingerprint {fingerprint} and mnemonic"
        )
        print(f"{mnemonic_to_string(mnemonic)}")

    except ValueError as e:
        print(e)
        return


def mnemonic_to_string(mnemonic_str):
    """
    Converts a menmonic to a user readable string in the terminal.
    """
    mnemonic = mnemonic_str.split()
    mnemonics_string = ""

    for i in range(0, len(mnemonic)):
        mnemonics_string += f"{i + 1}) {mnemonic[i]}"
        if i != len(mnemonic) - 1:
            mnemonics_string += ", "
        if (i + 1) % 6 == 0:
            mnemonics_string += "\n"

    return mnemonics_string


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
            create_puzzlehash_for_pk(
                master_sk_to_wallet_sk(sk, uint32(0)).get_g1()
            ).hex(),
        )
        assert seed is not None
        mnemonic = bytes_to_mnemonic(seed)
        mnemonic_string = mnemonic_to_string(mnemonic)
        print("  Mnemonic seed:")
        print(mnemonic_string)


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


def handler(args, parser):
    if args.command is None or len(args.command) < 1:
        help_message()
        parser.exit(1)

    root_path: Path = args.root_path
    if not root_path.is_dir():
        raise RuntimeError(
            "Please initialize (or migrate) your config directory with chia init."
        )

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
