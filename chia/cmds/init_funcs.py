from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from chia import __version__
from chia.cmds.configure import configure
from chia.consensus.coinbase import create_puzzlehash_for_pk
from chia.ssl.create_ssl import create_all_ssl
from chia.util.bech32m import encode_puzzle_hash
from chia.util.config import (
    create_default_chia_config,
    initial_config_file,
    load_config,
    lock_and_load_config,
    save_config,
    unflatten_properties,
)
from chia.util.db_version import set_db_version
from chia.util.keychain import Keychain
from chia.util.path import path_from_root
from chia.util.ssl_check import (
    DEFAULT_PERMISSIONS_CERT_FILE,
    DEFAULT_PERMISSIONS_KEY_FILE,
    RESTRICT_MASK_CERT_FILE,
    RESTRICT_MASK_KEY_FILE,
    check_and_fix_permissions_for_ssl_file,
    fix_ssl,
)
from chia.wallet.derive_keys import (
    _derive_path,
    _derive_path_unhardened,
    master_sk_to_pool_sk,
    master_sk_to_wallet_sk_intermediate,
    master_sk_to_wallet_sk_unhardened_intermediate,
)


def dict_add_new_default(updated: Dict[str, Any], default: Dict[str, Any], do_not_migrate_keys: Dict[str, Any]) -> None:
    for k in do_not_migrate_keys:
        if k in updated and do_not_migrate_keys[k] == "":
            updated.pop(k)
    for k, v in default.items():
        ignore = False
        if k in do_not_migrate_keys:
            do_not_data = do_not_migrate_keys[k]
            if isinstance(do_not_data, dict):
                ignore = False
            else:
                ignore = True
        if isinstance(v, dict) and k in updated and ignore is False:
            # If there is an intermediate key with empty string value, do not migrate all descendants
            if do_not_migrate_keys.get(k, None) == "":
                do_not_migrate_keys[k] = v
            dict_add_new_default(updated[k], default[k], do_not_migrate_keys.get(k, {}))
        elif k not in updated or ignore is True:
            updated[k] = v


def check_keys(new_root: Path, keychain: Optional[Keychain] = None) -> None:
    if keychain is None:
        keychain = Keychain()
    all_sks = keychain.get_all_private_keys()
    if len(all_sks) == 0:
        print("No keys are present in the keychain. Generate them with 'chia keys generate'")
        return None

    with lock_and_load_config(new_root, "config.yaml") as config:
        pool_child_pubkeys = [master_sk_to_pool_sk(sk).get_g1() for sk, _ in all_sks]
        all_targets = []
        stop_searching_for_farmer = "xch_target_address" not in config["farmer"]
        stop_searching_for_pool = "xch_target_address" not in config["pool"]
        number_of_ph_to_search = 50
        selected = config["selected_network"]
        prefix = config["network_overrides"]["config"][selected]["address_prefix"]

        intermediates = {}
        for sk, _ in all_sks:
            intermediates[bytes(sk)] = {
                "observer": master_sk_to_wallet_sk_unhardened_intermediate(sk),
                "non-observer": master_sk_to_wallet_sk_intermediate(sk),
            }

        for i in range(number_of_ph_to_search):
            if stop_searching_for_farmer and stop_searching_for_pool and i > 0:
                break
            for sk, _ in all_sks:
                intermediate_n = intermediates[bytes(sk)]["non-observer"]
                intermediate_o = intermediates[bytes(sk)]["observer"]

                all_targets.append(
                    encode_puzzle_hash(
                        create_puzzlehash_for_pk(_derive_path_unhardened(intermediate_o, [i]).get_g1()), prefix
                    )
                )
                all_targets.append(
                    encode_puzzle_hash(create_puzzlehash_for_pk(_derive_path(intermediate_n, [i]).get_g1()), prefix)
                )
                if all_targets[-1] == config["farmer"].get("xch_target_address") or all_targets[-2] == config[
                    "farmer"
                ].get("xch_target_address"):
                    stop_searching_for_farmer = True
                if all_targets[-1] == config["pool"].get("xch_target_address") or all_targets[-2] == config["pool"].get(
                    "xch_target_address"
                ):
                    stop_searching_for_pool = True

        # Set the destinations, if necessary
        updated_target: bool = False
        if "xch_target_address" not in config["farmer"]:
            print(
                f"Setting the xch destination for the farmer reward (1/8 plus fees, solo and pooling)"
                f" to {all_targets[0]}"
            )
            config["farmer"]["xch_target_address"] = all_targets[0]
            updated_target = True
        elif config["farmer"]["xch_target_address"] not in all_targets:
            print(
                f"WARNING: using a farmer address which we might not have the private"
                f" keys for. We searched the first {number_of_ph_to_search} addresses. Consider overriding "
                f"{config['farmer']['xch_target_address']} with {all_targets[0]}"
            )

        if "pool" not in config:
            config["pool"] = {}
        if "xch_target_address" not in config["pool"]:
            print(f"Setting the xch destination address for pool reward (7/8 for solo only) to {all_targets[0]}")
            config["pool"]["xch_target_address"] = all_targets[0]
            updated_target = True
        elif config["pool"]["xch_target_address"] not in all_targets:
            print(
                f"WARNING: using a pool address which we might not have the private"
                f" keys for. We searched the first {number_of_ph_to_search} addresses. Consider overriding "
                f"{config['pool']['xch_target_address']} with {all_targets[0]}"
            )
        if updated_target:
            print(
                f"To change the XCH destination addresses, edit the `xch_target_address` entries in"
                f" {(new_root / 'config' / 'config.yaml').absolute()}."
            )

        # Set the pool pks in the farmer
        pool_pubkeys_hex = set(bytes(pk).hex() for pk in pool_child_pubkeys)
        if "pool_public_keys" in config["farmer"]:
            for pk_hex in config["farmer"]["pool_public_keys"]:
                # Add original ones in config
                pool_pubkeys_hex.add(pk_hex)

        config["farmer"]["pool_public_keys"] = pool_pubkeys_hex
        save_config(new_root, "config.yaml", config)


def copy_files_rec(old_path: Path, new_path: Path) -> None:
    if old_path.is_file():
        print(f"{new_path}")
        new_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(old_path, new_path)
    elif old_path.is_dir():
        for old_path_child in old_path.iterdir():
            new_path_child = new_path / old_path_child.name
            copy_files_rec(old_path_child, new_path_child)


def migrate_from(
    old_root: Path,
    new_root: Path,
    manifest: List[str],
    do_not_migrate_settings: List[str],
) -> int:
    """
    Copy all the files in "manifest" to the new config directory.
    """
    if old_root == new_root:
        print("same as new path, exiting")
        return 1
    if not old_root.is_dir():
        print(f"{old_root} not found - this is ok if you did not install this version")
        return 0
    print(f"\n{old_root} found")
    print(f"Copying files from {old_root} to {new_root}\n")

    for f in manifest:
        old_path = old_root / f
        new_path = new_root / f
        copy_files_rec(old_path, new_path)

    # update config yaml with new keys

    with lock_and_load_config(new_root, "config.yaml") as config:
        config_str: str = initial_config_file("config.yaml")
        default_config: Dict[str, Any] = yaml.safe_load(config_str)
        flattened_keys = unflatten_properties({k: "" for k in do_not_migrate_settings})
        dict_add_new_default(config, default_config, flattened_keys)

        save_config(new_root, "config.yaml", config)

    create_all_ssl(new_root)

    return 1


def copy_cert_files(cert_path: Path, new_path: Path) -> None:
    for old_path_child in cert_path.glob("*.crt"):
        new_path_child = new_path / old_path_child.name
        copy_files_rec(old_path_child, new_path_child)
        check_and_fix_permissions_for_ssl_file(new_path_child, RESTRICT_MASK_CERT_FILE, DEFAULT_PERMISSIONS_CERT_FILE)

    for old_path_child in cert_path.glob("*.key"):
        new_path_child = new_path / old_path_child.name
        copy_files_rec(old_path_child, new_path_child)
        check_and_fix_permissions_for_ssl_file(new_path_child, RESTRICT_MASK_KEY_FILE, DEFAULT_PERMISSIONS_KEY_FILE)


def init(
    create_certs: Optional[Path],
    root_path: Path,
    fix_ssl_permissions: bool = False,
    testnet: bool = False,
    v1_db: bool = False,
) -> Optional[int]:
    if create_certs is not None:
        if root_path.exists():
            if os.path.isdir(create_certs):
                ca_dir: Path = root_path / "config/ssl/ca"
                if ca_dir.exists():
                    print(f"Deleting your OLD CA in {ca_dir}")
                    shutil.rmtree(ca_dir)
                print(f"Copying your CA from {create_certs} to {ca_dir}")
                copy_cert_files(create_certs, ca_dir)
                create_all_ssl(root_path)
            else:
                print(f"** Directory {create_certs} does not exist **")
        else:
            print(f"** {root_path} does not exist. Executing core init **")
            # sanity check here to prevent infinite recursion
            if (
                chia_init(
                    root_path,
                    fix_ssl_permissions=fix_ssl_permissions,
                    testnet=testnet,
                    v1_db=v1_db,
                )
                == 0
                and root_path.exists()
            ):
                return init(create_certs, root_path, fix_ssl_permissions)

            print(f"** {root_path} was not created. Exiting **")
            return -1
    else:
        return chia_init(root_path, fix_ssl_permissions=fix_ssl_permissions, testnet=testnet, v1_db=v1_db)

    return None


def chia_version_number() -> Tuple[str, str, str, str]:
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
        original_minor_ver_list = scm_minor_version.split("0b")
        major_release_number = str(1 - int(scm_major_version))  # decrement the major release for beta
        minor_release_number = scm_major_version
        patch_release_number = original_minor_ver_list[1]
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

    return major_release_number, minor_release_number, patch_release_number, dev_release_number


def chia_full_version_str() -> str:
    major, minor, patch, dev = chia_version_number()
    return f"{major}.{minor}.{patch}{dev}"


def chia_init(
    root_path: Path,
    *,
    should_check_keys: bool = True,
    fix_ssl_permissions: bool = False,
    testnet: bool = False,
    v1_db: bool = False,
) -> int:
    """
    Standard first run initialization or migration steps. Handles config creation,
    generation of SSL certs, and setting target addresses (via check_keys).

    should_check_keys can be set to False to avoid blocking when accessing a passphrase
    protected Keychain. When launching the daemon from the GUI, we want the GUI to
    handle unlocking the keychain.
    """
    chia_root = os.environ.get("CHIA_ROOT", None)
    if chia_root is not None:
        print(f"CHIA_ROOT is set to {chia_root}")

    print(f"Chia directory {root_path}")
    if root_path.is_dir() and Path(root_path / "config" / "config.yaml").exists():
        # This is reached if CHIA_ROOT is set, or if user has run chia init twice
        # before a new update.
        if testnet:
            configure(
                root_path,
                set_farmer_peer="",
                set_node_introducer="",
                set_fullnode_port="",
                set_harvester_port="",
                set_log_level="",
                enable_upnp="",
                set_outbound_peer_count="",
                set_peer_count="",
                testnet="true",
                peer_connect_timeout="",
                crawler_db_path="",
                crawler_minimum_version_count=None,
                seeder_domain_name="",
                seeder_nameserver="",
            )
        if fix_ssl_permissions:
            fix_ssl(root_path)
        if should_check_keys:
            check_keys(root_path)
        print(f"{root_path} already exists, no migration action taken")
        return -1

    create_default_chia_config(root_path)
    if testnet:
        configure(
            root_path,
            set_farmer_peer="",
            set_node_introducer="",
            set_fullnode_port="",
            set_harvester_port="",
            set_log_level="",
            enable_upnp="",
            set_outbound_peer_count="",
            set_peer_count="",
            testnet="true",
            peer_connect_timeout="",
            crawler_db_path="",
            crawler_minimum_version_count=None,
            seeder_domain_name="",
            seeder_nameserver="",
        )
    create_all_ssl(root_path)
    if fix_ssl_permissions:
        fix_ssl(root_path)
    if should_check_keys:
        check_keys(root_path)

    config: Dict[str, Any]

    db_path_replaced: str
    if v1_db:
        with lock_and_load_config(root_path, "config.yaml") as config:
            db_pattern = config["full_node"]["database_path"]
            new_db_path = db_pattern.replace("_v2_", "_v1_")
            config["full_node"]["database_path"] = new_db_path
            db_path_replaced = new_db_path.replace("CHALLENGE", config["selected_network"])
            db_path = path_from_root(root_path, db_path_replaced)

            db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(db_path) as connection:
                set_db_version(connection, 1)

            save_config(root_path, "config.yaml", config)

    else:
        config = load_config(root_path, "config.yaml")["full_node"]
        db_path_replaced = config["database_path"].replace("CHALLENGE", config["selected_network"])
        db_path = path_from_root(root_path, db_path_replaced)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # create new v2 db file
            with sqlite3.connect(db_path) as connection:
                set_db_version(connection, 2)
        except sqlite3.OperationalError:
            # db already exists, so we're good
            pass

    print("")
    print("To see your keys, run 'chia keys show --show-mnemonic-seed'")

    return 0
