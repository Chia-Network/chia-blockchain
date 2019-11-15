import argparse
import os
from definitions import ROOT_DIR
from yaml import safe_load, safe_dump
from secrets import token_bytes
from blspy import PrivateKey
from hashlib import sha256

key_config_filename = os.path.join(ROOT_DIR, "src", "config", "keys.yaml")


def str2bool(v: str) -> bool:
    if isinstance(v, bool):
        return v
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')


def main():
    """
    Allows replacing keys of farmer, harvester, and pool, all default to True.
    """

    parser = argparse.ArgumentParser(
        description="Chia key generator script."
    )
    parser.add_argument("-f", "--farmer", type=str2bool, nargs='?', const=True, default=True,
                        help="Regenerate farmer key")
    parser.add_argument("-a", "--harvester", type=str2bool, nargs='?', const=True, default=True,
                        help="Regenerate plot key seed")
    parser.add_argument("-p", "--pool", type=str2bool, nargs='?', const=True, default=True,
                        help="Regenerate pool keys")
    args = parser.parse_args()

    if os.path.isfile(key_config_filename):
        # If the file exists, warn the user
        yn = input(f"The keys file {key_config_filename} already exists. Are you sure"
                   f" you want to override the keys? Plots might become invalid. (y/n): ")
        if not (yn.lower() == "y" or yn.lower() == "yes"):
            quit()
    else:
        # Create the file if if doesn't exist
        open(key_config_filename, "a").close()

    key_config = safe_load(open(key_config_filename, "r"))
    if key_config is None:
        key_config = {}

    if args.farmer:
        # Replaces the farmer's private key. The farmer target allows spending
        # of the fees.
        farmer_sk = PrivateKey.from_seed(token_bytes(32))
        farmer_target = sha256(bytes(farmer_sk.get_public_key())).digest()
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
        pool_target = sha256(bytes(pool_sks[0].get_public_key())).digest()
        key_config["pool_sks"] = [bytes(pool_sk).hex() for pool_sk in pool_sks]
        key_config["pool_target"] = pool_target.hex()
        with open(key_config_filename, "w") as f:
            safe_dump(key_config, f)


if __name__ == "__main__":
    main()
