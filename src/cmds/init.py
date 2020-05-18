import os
import shutil

from argparse import Namespace, ArgumentParser
from typing import List, Tuple, Dict, Any
from blspy import ExtendedPrivateKey
from src.types.BLSSignature import BLSPublicKey
from src.consensus.coinbase import create_puzzlehash_for_pk
from src.util.config import unflatten_properties
from pathlib import Path

from src.util.config import (
    config_path_for_filename,
    create_default_chia_config,
    load_config,
    save_config,
    initial_config_file,
)
from src.util.path import mkdir, make_path_relative, path_from_root
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
    keys_config = load_config(new_root, "keys.yaml")

    wallet_sk = ExtendedPrivateKey.from_bytes(bytes.fromhex(keys_config["wallet_sk"]))
    wallet_target = create_puzzlehash_for_pk(
        BLSPublicKey(bytes(wallet_sk.public_child(0).get_public_key()))
    )
    if (
        wallet_target.hex() != keys_config["wallet_target"]
        or wallet_target.hex() != keys_config["pool_target"]
    ):
        keys_config["wallet_target"] = wallet_target.hex()
        keys_config["pool_target"] = wallet_target.hex()
        print(f"updating wallet target and pool target to {wallet_target.hex()}")
        save_config(new_root, "keys.yaml", keys_config)


def migrate_from(
    old_root: Path, new_root: Path, manifest: List[str], do_not_migrate_keys: List[str]
):
    """
    Copy all the files in "manifest" to the new config directory.
    """
    if old_root == new_root:
        print(f"same as new path, exiting")
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
    flattened_keys = unflatten_properties({k: "" for k in do_not_migrate_keys})
    dict_add_new_default(config, default_config, flattened_keys)

    save_config(new_root, "config.yaml", config)

    # migrate plots
    # for now, we simply leave them where they are
    # and make what may have been relative paths absolute
    if "config/trusted.key" in not_found or "config/trusted.key" in not_found:
        initialize_ssl(new_root)

    plots_config: Dict = load_config(new_root, "plots.yaml")

    plot_root = (
        load_config(new_root, "config.yaml").get("harvester", {}).get("plot_root", ".")
    )

    old_plots_root: Path = path_from_root(old_root, plot_root)
    new_plots_root: Path = path_from_root(new_root, plot_root)

    old_plot_paths = plots_config.get("plots", {})
    if len(old_plot_paths) == 0:
        print("no plots found, no plots migrated")
        return 1

    print("\nmigrating plots.yaml")

    new_plot_paths: Dict = {}
    for path, values in old_plot_paths.items():
        old_path_full = path_from_root(old_plots_root, path)
        new_path_relative = make_path_relative(old_path_full, new_plots_root)
        print(f"rewriting {path}\n as {new_path_relative}")
        new_plot_paths[str(new_path_relative)] = values
    plots_config_new: Dict = {"plots": new_plot_paths}
    save_config(new_root, "plots.yaml", plots_config_new)
    print("\nUpdated plots.yaml to point to where your existing plots are.")
    print(
        "\nYour plots have not been moved so be careful deleting old preferences folders."
    )

    print("\nchecking keys.yaml")
    check_keys(new_root)

    print("\nIf you want to move your plot files, you should also modify")
    print(f"{config_path_for_filename(new_root, 'plots.yaml')}")
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
    return chia_init(args)


def chia_init(args: Namespace):
    root_path: Path = args.root_path

    if os.environ.get("CHIA_ROOT", None) is not None:
        print(
            f"warning, your CHIA_ROOT is set to {os.environ['CHIA_ROOT']}. "
            f"Please unset the environment variable and run chia init again\n"
            f"or manually migrate config.yaml, plots.yaml and keys.yaml."
        )

    print(f"migrating to {root_path}")
    if root_path.is_dir():
        check_keys(root_path)
        print(f"{root_path} already exists, no migration action taken")
        return -1

    # These are the config keys that will not be migrated, and instead the default is used
    DO_NOT_MIGRATE_KEYS: List[str] = [
        "full_node.introducer_peer",
        "wallet.introducer_peer",
        "full_node.database_path",
        "full_node.simulator_database_path",
    ]

    # These are the files that will be migrated
    MANIFEST: List[str] = [
        "config/config.yaml",
        "config/plots.yaml",
        "config/keys.yaml",
        "config/trusted.crt",
        "config/trusted.key",
    ]

    PATH_MANIFEST_LIST: List[Tuple[Path, List[str]]] = [
        (Path(os.path.expanduser("~/.chia/beta-%s" % _)), MANIFEST)
        for _ in ["1.0b5.dev0", "1.0b4", "1.0b3", "1.0b2", "1.0b1"]
    ]

    for old_path, manifest in PATH_MANIFEST_LIST:
        r = migrate_from(old_path, root_path, manifest, DO_NOT_MIGRATE_KEYS)
        if r:
            break
    else:
        create_default_chia_config(root_path)
        initialize_ssl(root_path)
        print("Please generate your keys with 'chia generate keys'")

    return 0
