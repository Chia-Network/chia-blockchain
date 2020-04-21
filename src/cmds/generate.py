from secrets import token_bytes

from blspy import PrivateKey, ExtendedPrivateKey
from src.consensus.coinbase import create_puzzlehash_for_pk
from src.types.BLSSignature import BLSPublicKey
from src.util.config import config_path_for_filename, load_config, save_config, str2bool
from src.util.path import mkdir


def make_parser(parser):
    """
    Allows replacing keys of farmer, harvester, and pool, all default to True.
    """
    parser.add_argument(
        "-a",
        "--harvester",
        type=str2bool,
        nargs="?",
        const=True,
        default=True,
        help="Regenerate plot key seed",
    )
    parser.add_argument(
        "-p",
        "--pool",
        type=str2bool,
        nargs="?",
        const=True,
        default=True,
        help="Regenerate pool keys",
    )
    parser.add_argument(
        "-t",
        "--pooltarget",
        type=str2bool,
        nargs="?",
        const=True,
        default=True,
        help="Regenerate pool target",
    )
    parser.add_argument(
        "-w",
        "--wallet",
        type=str2bool,
        nargs="?",
        const=True,
        default=True,
        help="Regenerate wallet keys",
    )
    parser.add_argument(
        "keys", help='must the literal "keys"', type=str, nargs=1,
    )
    parser.set_defaults(function=generate)


def generate(args, parser):
    root_path = args.root_path
    keys_yaml = "keys.yaml"
    key_config_filename = config_path_for_filename(root_path, keys_yaml)
    if args.keys != ["keys"]:
        parser.print_help()
        print("\nTry `chia generate keys`")
        return 1
    if key_config_filename.exists():
        # If the file exists, warn the user
        yn = input(
            f"The keys file {key_config_filename} already exists. Are you sure"
            f" you want to override the keys? Plots might become invalid. (y/n): "
        )
        if not (yn.lower() == "y" or yn.lower() == "yes"):
            return 1
    else:
        # Create the file if if doesn't exist
        mkdir(key_config_filename.parent)
        open(key_config_filename, "a").close()

    key_config = load_config(root_path, keys_yaml)
    if key_config is None:
        key_config = {}

    wallet_target = None
    if args.wallet:
        wallet_sk = ExtendedPrivateKey.from_seed(token_bytes(32))
        wallet_target = create_puzzlehash_for_pk(
            BLSPublicKey(bytes(wallet_sk.public_child(0).get_public_key()))
        )
        key_config["wallet_sk"] = bytes(wallet_sk).hex()
        key_config["wallet_target"] = wallet_target.hex()
        save_config(root_path, keys_yaml, key_config)
    if args.harvester:
        # Replaces the harvester's sk seed. Used to generate plot private keys, which are
        # used to sign farmed blocks.
        key_config["sk_seed"] = token_bytes(32).hex()
        save_config(root_path, keys_yaml, key_config)
    if args.pool:
        # Replaces the pools keys and targes. Only useful if running a pool, or doing
        # solo farming. The pool target allows spending of the coinbase.
        pool_sks = [PrivateKey.from_seed(token_bytes(32)) for _ in range(2)]
        if wallet_target is None:
            pool_target = create_puzzlehash_for_pk(
                BLSPublicKey(bytes(pool_sks[0].get_public_key()))
            )
        else:
            pool_target = wallet_target
        key_config["pool_sks"] = [bytes(pool_sk).hex() for pool_sk in pool_sks]
        key_config["pool_target"] = pool_target.hex()
        save_config(root_path, keys_yaml, key_config)
    if args.pooltarget:
        # Compute a new pool target and save it to the config
        assert "wallet_target" in key_config
        key_config["pool_target"] = key_config["wallet_target"]
        save_config(root_path, keys_yaml, key_config)
