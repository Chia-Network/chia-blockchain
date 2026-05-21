import os
import binascii

from typing import Dict, List, Union
from pathlib import Path
from chia.util.config import load_config


def plunge_path_in_config_(fname: Path, config: Dict, path: List[str]):
    """
    Simple conveniece for finding a path in a config and reporting precisely what
    was expected that is missing.
    """
    index = 0

    while True:
        if index >= len(path):
            return config
        else:
            if not path[index] in config or config[path[index]] is None:
                raise Exception(f'could not find value {"/".join(path[:index])} in config {fname}')

            config = config[path[index]]
            index += 1


def get_agg_sig_me_additional_data(root_path: Union[str, Path] = None) -> bytes:
    """
    Loads the correct value for the AGG_SIG_ME_ADDITIONAL_DATA constant
    and returns it so it can be used conveniently by API consumers.

    Raise exception if not found.
    """
    if root_path is None:
        if "CHIA_ROOT" in os.environ:
            root_path = Path(os.environ["CHIA_ROOT"])
        else:
            root_path = Path(os.environ["HOME"]) / ".chia/mainnet"
    else:
        root_path = Path(root_path)

    want_file = root_path / "config/config.yaml"

    config = load_config(root_path, "config.yaml", None)

    selected_network = plunge_path_in_config_(want_file, config, ["selected_network"])

    # if the network has a different AGG_SIG_ME_ADDITIONAL_DATA then use it,
    # otherwise the network uses mainnet's genesis challenge.
    try:
        agg_sig_me_additional_data = plunge_path_in_config_(
            want_file,
            config,
            ["farmer", "network_overrides", "constants", selected_network, "AGG_SIG_ME_ADDITIONAL_DATA"],
        )
    except Exception:
        # We can't get additional data, so we'll go with the mainnet genesis
        # challenge.
        agg_sig_me_additional_data = plunge_path_in_config_(
            want_file, config, ["farmer", "network_overrides", "constants", "mainnet", "GENESIS_CHALLENGE"]
        )

    return bytes(binascii.unhexlify(agg_sig_me_additional_data))
