import os
import shutil

from pathlib import Path

from src.util.config import (
    config_path_for_filename,
    create_default_chia_config,
    load_config,
    save_config,
)
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.path import mkdir, make_path_relative, path_from_root


def make_parser(parser):
    parser.set_defaults(function=init)


def migrate_from(old_root, new_root, manifest):
    """
    Copy all the files in "manifest" to the new config directory.
    """
    if old_root == new_root:
        print(f"same as new path, exiting")
        return 1
    if not old_root.is_dir():
        print(f"{old_root} not found")
        return 0
    print(f"\n{old_root} found")
    print(f"Copying files from {old_root} to {new_root}\n")
    for f in manifest:
        old_path = old_root / f
        new_path = new_root / f
        if old_path.is_file():
            print(f"{new_path}")
            mkdir(new_path.parent)
            shutil.copy(old_path, new_path)
        else:
            print(f"{old_path} not found, skipping")

    # migrate plots
    # for now, we simply leave them where they are
    # and make what may have been relative paths absolute

    plots_config = load_config(new_root, "plots.yaml")

    plot_root = (
        load_config(new_root, "config.yaml").get("harvester", {}).get("plot_root", ".")
    )

    old_plots_root = path_from_root(old_root, plot_root)
    new_plots_root = path_from_root(new_root, plot_root)

    old_plot_paths = plots_config.get("plots", {})
    if len(old_plot_paths) == 0:
        print("no plots found, no plots migrated")
        return 1

    print("\nmigrating plots.yaml")

    new_plot_paths = {}
    for path, values in old_plot_paths.items():
        old_path_full = path_from_root(old_plots_root, path)
        new_path_relative = make_path_relative(old_path_full, new_plots_root)
        print(f"rewriting {path}\n as {new_path_relative}")
        new_plot_paths[str(new_path_relative)] = values
    plots_config_new = {"plots": new_plot_paths}
    save_config(new_root, "plots.yaml", plots_config_new)
    print("\nUpdated plots.yaml to point to where your existing plots are.")
    print(
        "\nYour plots have not been moved so be careful deleting old preferences folders."
    )
    print("If you want to move your plot files, you should also modify")
    print(f"{config_path_for_filename(new_root, 'plots.yaml')}")
    return 1


def init(args, parser):
    return chia_init()


def chia_init():
    root_path = DEFAULT_ROOT_PATH
    print(f"migrating to {root_path}")
    if root_path.is_dir():
        print(f"{root_path} already exists, no action taken")
        return -1

    MANIFEST = [
        "config/config.yaml",
        "config/plots.yaml",
        "config/keys.yaml",
        "db/blockchain_v3.db",
    ]

    PATH_MANIFEST_LIST = [
        (Path(os.path.expanduser("~/.chia/beta-%s" % _)), MANIFEST)
        for _ in ["1.0b3", "1.0b2", "1.0b1"]
    ]

    for old_path, manifest in PATH_MANIFEST_LIST:
        r = migrate_from(old_path, root_path, manifest)
        if r:
            break
    else:
        create_default_chia_config(root_path)
        print("Please generate your keys with chia-generate-keys")

    return 0
