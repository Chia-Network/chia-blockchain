from pathlib import Path

import pkg_resources

from chia.util.config import load_config, save_config


def patch_default_chia_seeder_config(root_path: Path, filename="config.yaml") -> None:
    """
    Checks if the dns: section exists in the config. If not, the default dns settings are appended to the file
    """

    existing_config = load_config(root_path, "config.yaml")

    if "dns" in existing_config:
        print("DNS section exists in config. No action required.")
        return

    print("DNS section does not exist in config. Patching...")
    config = load_config(root_path, "config.yaml")
    # The following ignores root_path when the second param is absolute, which this will be
    dns_config = load_config(root_path, pkg_resources.resource_filename(__name__, "initial-config.yaml"))

    # Patch in the values with anchors, since pyyaml tends to change
    # the anchors to things like id001, etc
    config["dns"] = dns_config["dns"]
    config["dns"]["network_overrides"] = config["network_overrides"]
    config["dns"]["selected_network"] = config["selected_network"]
    config["dns"]["logging"] = config["logging"]

    # When running as crawler, we default to a much lower client timeout
    config["full_node"]["peer_connect_timeout"] = 2

    save_config(root_path, "config.yaml", config)
