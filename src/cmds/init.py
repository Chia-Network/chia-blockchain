from src import __version__
import os
import shutil

from argparse import Namespace, ArgumentParser
from typing import List, Dict, Any
from src.util.keychain import Keychain

from src.util.config import unflatten_properties
from pathlib import Path
from src.consensus.coinbase import create_puzzlehash_for_pk
from src.util.ints import uint32

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
from src.wallet.derive_keys import master_sk_to_wallet_sk, master_sk_to_pool_sk
from src.util.chech32 import encode_puzzle_hash


def make_parser(parser: ArgumentParser):
    parser.set_defaults(function=init)


def dict_add_new_default(updated: Dict, default: Dict, do_not_migrate_keys: Dict[str, Any]):
    for k, v in default.items():
        if isinstance(v, dict) and k in updated:
            # If there is an intermediate key with empty string value, do not migrate all descendants
            if do_not_migrate_keys.get(k, None) == "":
                do_not_migrate_keys[k] = v
            dict_add_new_default(updated[k], default[k], do_not_migrate_keys.get(k, {}))
        elif k not in updated or k in do_not_migrate_keys:
            updated[k] = v


def check_keys(new_root):
    keychain: Keychain = Keychain()
    all_sks = keychain.get_all_private_keys()
    if len(all_sks) == 0:
        print("No keys are present in the keychain. Generate them with 'chia keys generate'")
        return

    config: Dict = load_config(new_root, "config.yaml")
    pool_child_pubkeys = [master_sk_to_pool_sk(sk).get_g1() for sk, _ in all_sks]
    all_targets = []
    stop_searching_for_farmer = "xch_target_address" not in config["farmer"]
    stop_searching_for_pool = "xch_target_address" not in config["pool"]
    for i in range(500):
        if stop_searching_for_farmer and stop_searching_for_pool and i > 0:
            break
        for sk, _ in all_sks:
            all_targets.append(
                encode_puzzle_hash(create_puzzlehash_for_pk(master_sk_to_wallet_sk(sk, uint32(i)).get_g1()))
            )
            if all_targets[-1] == config["farmer"].get("xch_target_address"):
                stop_searching_for_farmer = True
            if all_targets[-1] == config["pool"].get("xch_target_address"):
                stop_searching_for_pool = True

    # Set the destinations
    if "xch_target_address" not in config["farmer"]:
        print(f"Setting the xch destination address for coinbase fees reward to {all_targets[0]}")
        config["farmer"]["xch_target_address"] = all_targets[0]
    elif config["farmer"]["xch_target_address"] not in all_targets:
        print(
            f"WARNING: farmer using a puzzle hash which we don't have the private"
            f" keys for. Overriding "
            f"{config['farmer']['xch_target_address']} with {all_targets[0]}"
        )
        config["farmer"]["xch_target_address"] = all_targets[0]

    if "pool" not in config:
        config["pool"] = {}
    if "xch_target_address" not in config["pool"]:
        print(f"Setting the xch destination address for coinbase reward to {all_targets[0]}")
        config["pool"]["xch_target_address"] = all_targets[0]
    elif config["pool"]["xch_target_address"] not in all_targets:
        print(
            f"WARNING: pool using a puzzle hash which we don't have the private"
            f" keys for. Overriding "
            f"{config['pool']['xch_target_address']} with {all_targets[0]}"
        )
        config["pool"]["xch_target_address"] = all_targets[0]

    # Set the pool pks in the farmer
    pool_pubkeys_hex = set(bytes(pk).hex() for pk in pool_child_pubkeys)
    if "pool_public_keys" in config["farmer"]:
        for pk_hex in config["farmer"]["pool_public_keys"]:
            # Add original ones in config
            pool_pubkeys_hex.add(pk_hex)

    config["farmer"]["pool_public_keys"] = pool_pubkeys_hex
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

    def copy_files_rec(old_path: Path, new_path: Path):
        if old_path.is_file():
            print(f"{new_path}")
            mkdir(new_path.parent)
            shutil.copy(old_path, new_path)
        elif old_path.is_dir():
            for old_path_child in old_path.iterdir():
                new_path_child = new_path / old_path_child.name
                copy_files_rec(old_path_child, new_path_child)
        else:
            not_found.append(f)
            print(f"{old_path} not found, skipping")

    for f in manifest:
        old_path = old_root / f
        new_path = new_root / f
        copy_files_rec(old_path, new_path)

    # update config yaml with new keys
    config: Dict = load_config(new_root, "config.yaml")
    config_str: str = initial_config_file("config.yaml")
    default_config: Dict = yaml.safe_load(config_str)
    flattened_keys = unflatten_properties({k: "" for k in do_not_migrate_settings})
    dict_add_new_default(config, default_config, flattened_keys)

    save_config(new_root, "config.yaml", config)

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


def chiaMinorReleaseNumber():
    scm_full_version = __version__
    left_full_version = scm_full_version.split("+")

    version = left_full_version[0].split(".")

    scm_major_version = version[0]
    scm_minor_version = version[1]
    if len(version) > 2:
        smc_patch_version = version[2]
        patch_release_number = smc_patch_version
    else:
        smc_patch_version = ""

    major_release_number = scm_major_version
    minor_release_number = scm_minor_version
    dev_release_number = ""

    # If this is a beta dev release - get which beta it is
    if "0b" in scm_minor_version:
        orignial_minor_ver_list = scm_minor_version.split("0b")
        major_release_number = str(1 - int(scm_major_version))  # decrement the major release for beta
        minor_release_number = scm_major_version
        patch_release_number = orignial_minor_ver_list[1]
        if smc_patch_version and "dev" in smc_patch_version:
            dev_release_number = "." + smc_patch_version
    elif "0rc" in version[1]:
        original_minor_ver_list = scm_minor_version.split("0rc")
        major_release_number = str(1 - int(scm_major_version))  # decrement the major release for release candidate
        minor_release_number = str(int(scm_major_version) + 1)  # RC is 0.2.1 for RC 1
        patch_release_number = original_minor_ver_list[1]
        if smc_patch_version and "dev" in smc_patch_version:
            dev_release_number = "." + smc_patch_version
    else:
        major_release_number = scm_major_version
        minor_release_number = scm_minor_version
        patch_release_number = smc_patch_version
        dev_release_number = ""

    install_release_number = major_release_number + "." + minor_release_number
    if len(patch_release_number) > 0:
        install_release_number += "." + patch_release_number
    if len(dev_release_number) > 0:
        install_release_number += dev_release_number

    print(f"Install release number: {install_release_number}")
    return int(patch_release_number)


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
        "wallet.full_node_peer",
        "full_node.database_path",
        "wallet.database_path",
        "full_node.simulator_database_path",
        "farmer.full_node_peer.port",
        "timelord.full_node_peer.port",
        "full_node.port",
    ]

    # These are the files that will be migrated
    MANIFEST: List[str] = [
        "config",
        "db/blockchain_v22.db",
        "wallet",
    ]

    for versionnumber in range(chiaMinorReleaseNumber() - 1, 8, -1):
        old_path = Path(os.path.expanduser("~/.chia/beta-1.0b%s" % versionnumber))
        manifest = MANIFEST
        print(f"Checking {old_path}")
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
