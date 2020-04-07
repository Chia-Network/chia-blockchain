import os
import shutil

from pathlib import Path

from src.util.config import config_path_for_filename, initial_config_file, load_config, save_config
from src.util.path import make_path_relative, mkdir, path_from_root


def make_parser(parser):
    parser.set_defaults(function=init)


def migrate_from(old_dir, new_dir, manifest):
    """
    Copy all the files in "manifest" to the new config directory.
    """
    if old_dir == new_dir:
        print(f"same as new path, exiting")
        return 1
    if not old_dir.is_dir():
        print(f"{old_dir} not found")
        return 0
    print(f"\n{old_dir} found")
    print(f"Copying files from {old_dir} to {new_dir}\n")
    for f in manifest:
        old_path = old_dir / f
        new_path = new_dir / f
        if old_path.is_file():
            print(f"{new_path}")
            mkdir(new_path.parent)
            shutil.copy(old_path, new_path)
        else:
            print(f"{old_path} not found, skipping")

    # migrate plots
    # for now, we simply leave them where they are
    # and make what may have been relative paths absolute

    old_config = load_config("config.yaml")
    plot_root = old_config.get_dpath("harvester.plot_root", "plots")

    plots_config = load_config("plots.yaml")
    old_plot_paths = plots_config.get_dpath("plots", [])
    if len(old_plot_paths) == 0:
        print("no plots found, no plots migrated")
        return 1

    print("\nmigrating plots.yaml")
    new_plot_paths = {}
    for path, values in old_plot_paths.items():
        old_path = path_from_root(path, old_dir)
        new_plot_path = make_path_relative(old_path, new_dir)
        print(f"rewriting {path}\n as {new_plot_path}")
        new_plot_paths[str(new_plot_path)] = values
    plots_config.set_dpath("plots", new_plot_paths)
    save_config("plots.yaml", new_plot_paths)
    print("\nUpdated plots.yaml to point to where your existing plots are.")
    print("\nYour plots have not been moved so be careful to deleting old preferences folders.")
    print("If you want to move your plot files, you should also modify")
    print(f"{config_path_for_filename('plots.yaml')}")
    return 1


def init(args, parser):
    new_path = path_from_root(".")
    print(f"migrating to {new_path}")
    if new_path.is_dir():
        print(f"{new_path} already exists, no action taken")
        return -1

    MANIFEST = [
        "config/config.yaml",
        "config/plots.yaml",
        "config/keys.yaml",
        "wallet/db/blockchain_wallet_v4.db",
        "db/blockchain_v3.db",
    ]

    PATH_MANIFEST_LIST = [
        (Path(os.path.expanduser("~/.chia/beta-%s" % _)), MANIFEST) for _ in ["1.0b1"]
    ]

    for old_path, manifest in PATH_MANIFEST_LIST:
        r = migrate_from(old_path, new_path, manifest)
        if r:
            break
    else:
        create_new_template(new_path)

    return 0


def create_new_template(path: Path) -> None:
    filename = "config.yaml"
    default_config_file_data = initial_config_file(filename)
    with open(config_path_for_filename(filename), "w") as f:
        f.write(default_config_file_data)
    save_config("plots.yaml", {})
    print("Please generate your keys with chia-generate-keys")
