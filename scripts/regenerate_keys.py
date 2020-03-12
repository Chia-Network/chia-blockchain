import argparse
from secrets import token_bytes

from blspy import PrivateKey, ExtendedPrivateKey
from yaml import safe_dump, safe_load
from src.pool import create_puzzlehash_for_pk
from src.types.hashable.BLSSignature import BLSPublicKey

from definitions import ROOT_DIR

key_config_filename = ROOT_DIR / "config" / "keys.yaml"


def str2bool(v: str) -> bool:
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "y", "1"):
        return True
    elif v.lower() in ("no", "false", "f", "n", "0"):
        return False
    else:
        raise argparse.ArgumentTypeError("Boolean value expected.")


def main():
    """
    Allows replacing keys of farmer, harvester, and pool, all default to True.
    """

    parser = argparse.ArgumentParser(description="Chia key generator script.")
    parser.add_argument(
        "-f",
        "--farmer",
        type=str2bool,
        nargs="?",
        const=True,
        default=True,
        help="Regenerate farmer key",
    )
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
        "-w",
        "--wallet",
        type=str2bool,
        nargs="?",
        const=True,
        default=True,
        help="Regenerate wallet keys",
    )
    args = parser.parse_args()

    if key_config_filename.exists():
        # If the file exists, warn the user
        yn = input(
            f"The keys file {key_config_filename} already exists. Are you sure"
            f" you want to override the keys? Plots might become invalid. (y/n): "
        )
        if not (yn.lower() == "y" or yn.lower() == "yes"):
            quit()
    else:
        # Create the file if if doesn't exist
        open(key_config_filename, "a").close()

    key_config = safe_load(open(key_config_filename, "r"))
    if key_config is None:
        key_config = {}

    wallet_target = None
    if args.wallet:
        wallet_sk = ExtendedPrivateKey.from_seed(token_bytes(32))
        wallet_target = create_puzzlehash_for_pk(
            BLSPublicKey(bytes(wallet_sk.get_public_key()))
        )
        key_config["wallet_sk"] = bytes(wallet_sk).hex()
        with open(key_config_filename, "w") as f:
            safe_dump(key_config, f)
    if args.farmer:
        # Replaces the farmer's private key. The farmer target allows spending
        # of the fees.
        farmer_sk = PrivateKey.from_seed(token_bytes(32))
        if wallet_target is None:
            farmer_target = create_puzzlehash_for_pk(
                BLSPublicKey(bytes(wallet_sk.get_public_key()))
            )
        else:
            farmer_target = wallet_target
        key_config["farmer_sk"] = bytes(farmer_sk).hex()
        key_config["farmer_target"] = farmer_target.hex()
        with open(key_config_filename, "w") as f:
            safe_dump(key_config, f)
    if args.harvester:
        # Replaces the harvester's sk seed. Used to generate plot private keys, which are
        # used to sign farmed blocks.
        key_config["sk_seed"] = token_bytes(32).hex()
        with open(key_config_filename, "w") as f:
            safe_dump(key_config, f)
    if args.pool:
        # Replaces the pools keys and targes. Only useful if running a pool, or doing
        # solo farming. The pool target allows spending of the coinbase.
        pool_sks = [PrivateKey.from_seed(token_bytes(32)) for _ in range(2)]
        if wallet_target is None:
            pool_target = create_puzzlehash_for_pk(
                BLSPublicKey(bytes(wallet_sk.get_public_key()))
            )
        else:
            pool_target = wallet_target
        key_config["pool_sks"] = [bytes(pool_sk).hex() for pool_sk in pool_sks]
        key_config["pool_target"] = pool_target.hex()
        with open(key_config_filename, "w") as f:
            safe_dump(key_config, f)


if __name__ == "__main__":
    main()
