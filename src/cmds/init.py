from src import __version__
import os
import shutil

from argparse import Namespace, ArgumentParser
from typing import List, Dict, Any, Tuple

from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.keychain import Keychain

from src.util.config import unflatten_properties
from pathlib import Path
from src.consensus.coinbase import create_puzzlehash_for_pk
from src.util.ints import uint32

from src.util.config import (
    create_default_chia_config,
    load_config,
    save_config,
    initial_config_file,
)
from src.util.path import mkdir
import yaml

from src.ssl.create_ssl import get_chia_ca_crt_key, generate_ca_signed_cert, make_ca_cert
from src.wallet.derive_keys import master_sk_to_wallet_sk, master_sk_to_pool_sk
from src.util.bech32m import encode_puzzle_hash


private_node_names = {"full_node", "wallet", "farmer", "harvester", "timelord", "daemon"}
public_node_names = {"full_node", "wallet", "farmer", "introducer", "timelord"}


def help_message():
    print("usage: chia init")
    print(
        """
        chia init (migrate previous version configuration to current)
        chia init -c [directory] (creates new TLS certificates signed by your CA in [directory])
            Follow these steps to create new certifcates for a remote harvester:
            - Make a copy of your Farming Machine CA directory: ~/.chia/[version]/config/ssl/ca
            - Shut down all chia daemon processes with `chia stop all -d`
            - Run `chia init -c [directory]` on your remote harvester,
              where [directory] is the the copy of your Farming Machine CA directory
            - Get more details on remote harvester on Chia wiki:
              https://github.com/Chia-Network/chia-blockchain/wiki/Farming-on-many-machines
        """
    )


def make_parser(parser):
    parser.add_argument(
        "-c",
        "--create_certs",
        help="Create new SSL certificates based on CA in [directory]",
        type=Path,
        default=None,
    )
    parser.set_defaults(function=init)
    parser.print_help = lambda self=parser: help_message()


def dict_add_new_default(updated: Dict, default: Dict, do_not_migrate_keys: Dict[str, Any]):
    for k in do_not_migrate_keys:
        if k in updated:
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
    number_of_ph_to_search = 500
    for i in range(number_of_ph_to_search):
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
            f"WARNING: using a farmer address which we don't have the private"
            f" keys for. We searched the first {number_of_ph_to_search} addresses. Consider overriding "
            f"{config['farmer']['xch_target_address']} with {all_targets[0]}"
        )

    if "pool" not in config:
        config["pool"] = {}
    if "xch_target_address" not in config["pool"]:
        print(f"Setting the xch destination address for coinbase reward to {all_targets[0]}")
        config["pool"]["xch_target_address"] = all_targets[0]
    elif config["pool"]["xch_target_address"] not in all_targets:
        print(
            f"WARNING: using a pool address which we don't have the private"
            f" keys for. We searched the first {number_of_ph_to_search} addresses. Consider overriding "
            f"{config['pool']['xch_target_address']} with {all_targets[0]}"
        )

    # Set the pool pks in the farmer
    pool_pubkeys_hex = set(bytes(pk).hex() for pk in pool_child_pubkeys)
    if "pool_public_keys" in config["farmer"]:
        for pk_hex in config["farmer"]["pool_public_keys"]:
            # Add original ones in config
            pool_pubkeys_hex.add(pk_hex)

    config["farmer"]["pool_public_keys"] = pool_pubkeys_hex
    save_config(new_root, "config.yaml", config)


def copy_files_rec(old_path: Path, new_path: Path):
    if old_path.is_file():
        print(f"{new_path}")
        mkdir(new_path.parent)
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

    create_all_ssl(new_root)

    return 1


def create_all_ssl(root: Path):
    # remove old key and crt
    config_dir = root / "config"
    old_key_path = config_dir / "trusted.key"
    old_crt_path = config_dir / "trusted.crt"
    if old_key_path.exists():
        print(f"Old key not needed anymore, deleting {old_key_path}")
        os.remove(old_key_path)
    if old_crt_path.exists():
        print(f"Old crt not needed anymore, deleting {old_crt_path}")
        os.remove(old_crt_path)

    ssl_dir = config_dir / "ssl"
    if not ssl_dir.exists():
        ssl_dir.mkdir()
    ca_dir = ssl_dir / "ca"
    if not ca_dir.exists():
        ca_dir.mkdir()

    private_ca_key_path = ca_dir / "private_ca.key"
    private_ca_crt_path = ca_dir / "private_ca.crt"
    chia_ca_crt, chia_ca_key = get_chia_ca_crt_key()
    chia_ca_crt_path = ca_dir / "chia_ca.crt"
    chia_ca_key_path = ca_dir / "chia_ca.key"
    chia_ca_crt_path.write_bytes(chia_ca_crt)
    chia_ca_key_path.write_bytes(chia_ca_key)

    if not private_ca_key_path.exists() or not private_ca_crt_path.exists():
        # Create private CA
        print(f"Can't find private CA, creating a new one in {root} to generate TLS certificates")
        make_ca_cert(private_ca_crt_path, private_ca_key_path)
        # Create private certs for each node
        ca_key = private_ca_key_path.read_bytes()
        ca_crt = private_ca_crt_path.read_bytes()
        generate_ssl_for_nodes(ssl_dir, ca_crt, ca_key, True)
    else:
        # This is entered when user copied over private CA
        print(f"Found private CA in {root}, using it to generate TLS certificates")
        ca_key = private_ca_key_path.read_bytes()
        ca_crt = private_ca_crt_path.read_bytes()
        generate_ssl_for_nodes(ssl_dir, ca_crt, ca_key, True)

    chia_ca_crt, chia_ca_key = get_chia_ca_crt_key()
    generate_ssl_for_nodes(ssl_dir, chia_ca_crt, chia_ca_key, False, overwrite=False)


def generate_ssl_for_nodes(ssl_dir: Path, ca_crt: bytes, ca_key: bytes, private: bool, overwrite=True):
    if private:
        names = private_node_names
    else:
        names = public_node_names

    for node_name in names:
        node_dir = ssl_dir / node_name
        if not node_dir.exists():
            node_dir.mkdir()
        if private:
            prefix = "private"
        else:
            prefix = "public"
        key_path = node_dir / f"{prefix}_{node_name}.key"
        crt_path = node_dir / f"{prefix}_{node_name}.crt"
        if key_path.exists() and crt_path.exists() and overwrite is False:
            continue
        generate_ca_signed_cert(ca_crt, ca_key, crt_path, key_path)


def init(args: Namespace, parser: ArgumentParser):
    if args.create_certs is not None:
        if args.root_path.exists():
            if os.path.isdir(args.create_certs):
                ca_dir: Path = args.root_path / "config/ssl/ca"
                if ca_dir.exists():
                    print(f"Deleting your OLD CA in {ca_dir}")
                    shutil.rmtree(ca_dir)
                print(f"Copying your CA from {args.create_certs} to {ca_dir}")
                copy_files_rec(args.create_certs, ca_dir)
                create_all_ssl(args.root_path)
            else:
                print(f"** Directory {args.create_certs} does not exist **")
        else:
            print(f"** {args.root_path} does not exist **")
            print("** please run `chia init` to migrate or create new config files **")
    else:
        return chia_init(args.root_path)


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


def chia_minor_release_number():
    res = int(chia_version_number()[2])
    print(f"Install release number: {res}")
    return res


def chia_full_version_str() -> str:
    major, minor, patch, dev = chia_version_number()
    return f"{major}.{minor}.{patch}{dev}"


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
        "harvester.num_threads",
        "min_mainnet_k_size",
        "max_inbound_wallet",
        "max_inbound_farmer",
        "max_inbound_timelord",
        "ssl.crt",
        "ssl.key",
        "harvester.ssl",
        "farmer.ssl",
        "timelord.ssl",
        "full_node.ssl",
        "introducer.ssl",
        "wallet.ssl",
        "network_genesis_challenges",
        "full_node.network_genesis_challenges",
        "harvester.network_genesis_challenges",
        "farmer.network_genesis_challenges",
        "wallet.network_genesis_challenges",
        "introducer.network_genesis_challenges",
        "pool.network_genesis_challenges",
        "ui.network_genesis_challenges",
        "timelord.network_genesis_challenges",
        "selected_network",
        "full_node.selected_network",
        "harvester.selected_network",
        "farmer.selected_network",
        "wallet.selected_network",
        "introducer.selected_network",
        "pool.selected_network",
        "ui.selected_network",
        "timelord.selected_network",
        "farmer.xch_target_address",
        "pool.xch_target_address",
    ]

    # These are the files that will be migrated
    MANIFEST: List[str] = [
        "config",
        # "db/blockchain_v27_2.db",
        # "wallet",
    ]

    manifest = MANIFEST

    # Migrates rc1
    rc1_path = Path(os.path.expanduser("~/.chia/1.0rc1"))
    if rc1_path.is_dir():
        r = migrate_from(rc1_path, root_path, manifest, DO_NOT_MIGRATE_SETTINGS)
        if r:
            check_keys(root_path)
            return 0

    # Migrates windows beta27
    b27_windows_path = Path(os.path.expanduser("~/.chia/beta-0.1.27"))
    if b27_windows_path.is_dir():
        r = migrate_from(b27_windows_path, root_path, manifest, DO_NOT_MIGRATE_SETTINGS)
        if r:
            check_keys(root_path)
            return 0

    # Version 19 is the first version that used the bech32m addresses
    for version_number in range(27, 18, -1):
        old_path = Path(os.path.expanduser("~/.chia/beta-1.0b%s" % version_number))
        print(f"Checking {old_path}")
        # This is reached if the user has updated the application, and therefore a new configuration
        # folder must be used. First we migrate the config fies, and then we migrate the private keys.
        r = migrate_from(old_path, root_path, manifest, DO_NOT_MIGRATE_SETTINGS)
        if r:
            check_keys(root_path)
            break
    else:
        create_default_chia_config(root_path)
        create_all_ssl(root_path)
        check_keys(root_path)
        print("")
        print("To see your keys, run 'chia keys show'")

    return 0


if __name__ == "__main__":
    chia_init(DEFAULT_ROOT_PATH)
