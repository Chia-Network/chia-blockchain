import os
import shutil

from argparse import Namespace, ArgumentParser
from typing import List, Tuple, Dict, Any
from src.util.keychain import Keychain

from src.util.config import unflatten_properties
from pathlib import Path
from src.types.BLSSignature import BLSPublicKey
from src.consensus.coinbase import create_puzzlehash_for_pk

from src.util.config import (
    config_path_for_filename,
    create_default_chia_config,
    load_config,
    save_config,
    initial_config_file,
)
from src.util.path import mkdir
import yaml

from src.ssl.create_ssl import generate_selfsigned_cert


def make_parser(parser: ArgumentParser):
    parser.set_defaults(function=init)


def dict_add_new_default(
    updated: Dict, default: Dict, do_not_migrate_keys: Dict[str, Any]
):
    for k, v in default.items():
        if isinstance(v, dict) and k in updated:
            # If there is an intermediate key with empty string value, do not migrate all decendants
            if do_not_migrate_keys.get(k, None) == "":
                do_not_migrate_keys[k] = v
            dict_add_new_default(updated[k], default[k], do_not_migrate_keys.get(k, {}))
        elif k not in updated or k in do_not_migrate_keys:
            updated[k] = v


def check_keys(new_root):
    keychain: Keychain = Keychain()
    all_pubkeys = keychain.get_all_public_keys()
    if len(all_pubkeys) == 0:
        print(
            "No keys are present in the keychain. Generate them with 'chia keys generate'"
        )
        return
    all_child_pubkeys = [epk.public_child(0).get_public_key() for epk in all_pubkeys]
    all_targets = [
        create_puzzlehash_for_pk(BLSPublicKey(bytes(pk))).hex()
        for pk in all_child_pubkeys
    ]

    config: Dict = load_config(new_root, "config.yaml")

    # Set the destinations
    if "xch_target_puzzle_hash" not in config["farmer"]:
        print(
            f"Setting the xch destination address for coinbase fees reward to {all_targets[0]}"
        )
        config["farmer"]["xch_target_puzzle_hash"] = all_targets[0]
    elif config["farmer"]["xch_target_puzzle_hash"] not in all_targets:
        assert len(config["farmer"]["xch_target_puzzle_hash"]) == 64
        print(
            "WARNING: farmer using a puzzle hash which we don't have the private keys for"
        )

    if "pool" in config:
        if "xch_target_puzzle_hash" not in config["pool"]:
            print(
                f"Setting the xch destination address for coinbase reward to {all_targets[0]}"
            )
            config["pool"]["xch_target_puzzle_hash"] = all_targets[0]
        elif config["pool"]["xch_target_puzzle_hash"] not in all_targets:
            assert len(config["pool"]["xch_target_puzzle_hash"]) == 64
            print(
                "WARNING: pool using a puzzle hash which we don't have the private keys for"
            )

    # Set the pool pks in the farmer
    all_pubkeys_hex = set([bytes(pk).hex() for pk in all_child_pubkeys])
    if "pool_public_keys" in config["farmer"]:
        for pk_hex in config["farmer"]["pool_public_keys"]:
            # Add original ones in config
            all_pubkeys_hex.add(pk_hex)

    config["farmer"]["pool_public_keys"] = all_pubkeys_hex
    save_config(new_root, "config.yaml", config)


def migrate_from(
    old_root: Path,
    new_root: Path,
    manifest: List[str],
    do_not_migrate_settings: List[str],
):
    """
    Copy all the files in "manifest" to the new config directory.
    """
    if old_root == new_root:
        print("same as new path, exiting")
        return 1
    if not old_root.is_dir():
        print(f"{old_root} not found - this is ok if you did not install this version.")
        return 0
    print(f"\n{old_root} found")
    print(f"Copying files from {old_root} to {new_root}\n")
    not_found = []
    for f in manifest:
        old_path = old_root / f
        new_path = new_root / f
        if old_path.is_file():
            print(f"{new_path}")
            mkdir(new_path.parent)
            shutil.copy(old_path, new_path)
        else:
            not_found.append(f)
            print(f"{old_path} not found, skipping")
    # update config yaml with new keys
    config: Dict = load_config(new_root, "config.yaml")
    config_str: str = initial_config_file("config.yaml")
    default_config: Dict = yaml.safe_load(config_str)
    flattened_keys = unflatten_properties({k: "" for k in do_not_migrate_settings})
    dict_add_new_default(config, default_config, flattened_keys)

    save_config(new_root, "config.yaml", config)

    # migrate plots
    # for now, we simply leave them where they are
    # and make what may have been relative paths absolute
    if "config/trusted.key" in not_found or "config/trusted.key" in not_found:
        initialize_ssl(new_root)

    return 1


def initialize_ssl(root_path: Path):
    cert, key = generate_selfsigned_cert()
    path_crt = config_path_for_filename(root_path, "trusted.crt")
    path_key = config_path_for_filename(root_path, "trusted.key")
    with open(path_crt, "w") as f:
        f.write(cert)
    with open(path_key, "w") as f:
        f.write(key)


def init(args: Namespace, parser: ArgumentParser):
    return chia_init(args.root_path)


def chia_init(root_path: Path):
    if os.environ.get("CHIA_ROOT", None) is not None:
        print(
            f"warning, your CHIA_ROOT is set to {os.environ['CHIA_ROOT']}. "
            f"Please unset the environment variable and run chia init again\n"
            f"or manually migrate config.yaml."
        )

    print(f"Chia directory {root_path}")
    if root_path.is_dir() and Path(root_path / "config" / "config.yaml").exists():
        # This is reached if CHIA_ROOT is set, or if user has run chia init twice
        # before a new update.
        check_keys(root_path)

        print(f"{root_path} already exists, no migration action taken")
        return -1

    # These are the config keys that will not be migrated, and instead the default is used
    DO_NOT_MIGRATE_SETTINGS: List[str] = [
        "full_node.introducer_peer",
        "wallet.introducer_peer",
        "full_node.database_path",
        "full_node.simulator_database_path",
    ]

    # These are the files that will be migrated
    MANIFEST: List[str] = [
        "config/config.yaml",
        "config/trusted.crt",
        "config/trusted.key",
    ]

    PATH_MANIFEST_LIST: List[Tuple[Path, List[str]]] = [
        (Path(os.path.expanduser("~/.chia/beta-%s" % _)), MANIFEST)
        for _ in [
            # "1.0b8",
        ]
    ]

    for old_path, manifest in PATH_MANIFEST_LIST:
        # This is reached if the user has updated the application, and therefore a new configuration
        # folder must be used. First we migrate the config fies, and then we migrate the private keys.
        r = migrate_from(old_path, root_path, manifest, DO_NOT_MIGRATE_SETTINGS)
        if r:
            check_keys(root_path)
            break
    else:
        create_default_chia_config(root_path)
        initialize_ssl(root_path)
        check_keys(root_path)
        print("")
        print("To see your keys, run 'chia keys show'")

    return 0
