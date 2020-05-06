from src.util.keychain import (
    generate_mnemonic,
    bytes_to_mnemonic,
    Keychain,
    seed_from_mnemonic,
)


def make_parser(parser):
    """
    Allows replacing keys of farmer, harvester, and pool, all default to True.
    """

    parser.add_argument(
        "-m",
        "--mnemonic",
        type=str,
        nargs=24,
        default=None,
        help="Enter mnemonic you want to use",
    )

    parser.add_argument(
        "command", help="", type=str, nargs=1,
    )
    parser.set_defaults(function=handler)


keychain: Keychain = Keychain.create()


def generate():
    mnemonic = generate_mnemonic()
    mnemonics_string = mnemonic_to_string(mnemonic)
    print("Mnemonic:")
    print(mnemonics_string)


def set_key(args, key_type):
    try:
        mnemonic = args.mnemonic
        print(f"Adding mnemonic: {mnemonic_to_string(mnemonic)}")
        seed = seed_from_mnemonic(mnemonic)

        if key_type == "wallet":
            keychain.set_wallet_seed(seed)
            return
        elif key_type == "pool":
            keychain.set_pool_seed(seed)
            return
        elif key_type == "harvester":
            keychain.set_harvested_seed(seed)
            return

        print("Invalid key type")
    except ValueError as e:
        print(e)
        return


def mnemonic_to_string(mnemonic):
    mnemonics_string = ""

    for i in range(0, 24):
        mnemonics_string += f"{i + 1}) {mnemonic[i]}, "
        if (i + 1) % 6 == 0:
            mnemonics_string += "\n"

    return mnemonics_string


def show_mnemonics(key):
    if key == "wallet":
        entropy = keychain.get_wallet_seed()
    elif key == "harvester":
        entropy = keychain.get_harvester_seed()
    elif key == "pool":
        entropy = keychain.get_pool_seed()
    else:
        print("Wrong key type")
        return
    if entropy is None:
        print(f"No key for {key}")
        return
    mnemonic = bytes_to_mnemonic(entropy)
    mnemonic_string = mnemonic_to_string(mnemonic)
    print(mnemonic_string)


def handler(args, parser):
    command_list = [
        "generate",
        "set_wallet_key",
        "set_harvester_key",
        "set_pool_key",
        "show_wallet_key",
        "show_harvester_key",
        "show_pool_key",
        "delete",
    ]

    command = args.command[0]
    if command not in command_list:
        print(f"Available commands: {command_list}")
        return 1

    if command == "generate":
        generate()
    elif command == "set_wallet_key":
        set_key(args, "wallet")
    elif command == "set_harvester_key":
        set_key(args, "harvester")
    elif command == "set_pool_key":
        set_key(args, "pool")
    elif command == "show_wallet_key":
        show_mnemonics("wallet")
    elif command == "show_harvester_key":
        show_mnemonics("harvester")
    elif command == "show_pool_key":
        show_mnemonics("pool")
    elif command == "delete":
        keychain.delete_all_keys()
