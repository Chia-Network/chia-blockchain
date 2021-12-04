from pathlib import Path

import pkg_resources

from chia.util.config import load_config, save_config


def patch_default_seeder_config(root_path: Path, filename="config.yaml") -> None:
    """
    Checks if the seeder: section exists in the config. If not, the default seeder settings are appended to the file
    """

    existing_config = load_config(root_path, "config.yaml")

    if "seeder" in existing_config:
        print("Chia Seeder section exists in config. No action required.")
        return

    print("Chia Seeder section does not exist in config. Patching...")
    config = load_config(root_path, "config.yaml")
    # The following ignores root_path when the second param is absolute, which this will be
    seeder_config = load_config(root_path, pkg_resources.resource_filename("chia.util", "initial-config.yaml"))

    # Patch in the values with anchors, since pyyaml tends to change
    # the anchors to things like id001, etc
    config["seeder"] = seeder_config["seeder"]
    config["seeder"]["network_overrides"] = config["network_overrides"]
    config["seeder"]["selected_network"] = config["selected_network"]
    config["seeder"]["logging"] = config["logging"]

    # When running as crawler, we default to a much lower client timeout
    config["full_node"]["peer_connect_timeout"] = 2

    save_config(root_path, "config.yaml", config)
