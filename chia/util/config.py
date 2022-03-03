import argparse
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

import pkg_resources
import yaml
from typing_extensions import Literal

from chia.util.path import mkdir

PEER_DB_PATH_KEY_DEPRECATED = "peer_db_path"  # replaced by "peers_file_path"
WALLET_PEERS_PATH_KEY_DEPRECATED = "wallet_peers_path"  # replaced by "wallet_peers_file_path"


def initial_config_file(filename: Union[str, Path]) -> str:
    return pkg_resources.resource_string(__name__, f"initial-{filename}").decode()


def create_default_chia_config(root_path: Path, filenames=["config.yaml"]) -> None:
    for filename in filenames:
        default_config_file_data: str = initial_config_file(filename)
        path: Path = config_path_for_filename(root_path, filename)
        tmp_path: Path = path.with_suffix("." + str(os.getpid()))
        mkdir(path.parent)
        with open(tmp_path, "w") as f:
            f.write(default_config_file_data)
        try:
            os.replace(str(tmp_path), str(path))
        except PermissionError:
            shutil.move(str(tmp_path), str(path))


def config_path_for_filename(root_path: Path, filename: Union[str, Path]) -> Path:
    path_filename = Path(filename)
    if path_filename.is_absolute():
        return path_filename
    return root_path / "config" / filename


def save_config(root_path: Path, filename: Union[str, Path], config_data: Any):
    path: Path = config_path_for_filename(root_path, filename)
    tmp_path: Path = path.with_suffix("." + str(os.getpid()))
    with open(tmp_path, "w") as f:
        yaml.safe_dump(config_data, f)
    try:
        os.replace(str(tmp_path), path)
    except PermissionError:
        shutil.move(str(tmp_path), str(path))


def load_config(
    root_path: Path,
    filename: Union[str, Path],
    sub_config: Optional[str] = None,
    exit_on_error=True,
) -> Dict:
    path = config_path_for_filename(root_path, filename)
    if not path.is_file():
        if not exit_on_error:
            raise ValueError("Config not found")
        print(f"can't find {path}")
        print("** please run `chia init` to migrate or create new config files **")
        # TODO: fix this hack
        sys.exit(-1)
    r = yaml.safe_load(open(path, "r"))
    if sub_config is not None:
        r = r.get(sub_config)
    return r


def load_config_cli(root_path: Path, filename: str, sub_config: Optional[str] = None) -> Dict:
    """
    Loads configuration from the specified filename, in the config directory,
    and then overrides any properties using the passed in command line arguments.
    Nested properties in the config file can be used in the command line with ".",
    for example --farmer_peer.host. Does not support lists.
    """
    config = load_config(root_path, filename, sub_config)

    flattened_props = flatten_properties(config)
    parser = argparse.ArgumentParser()

    for prop_name, value in flattened_props.items():
        if type(value) is list:
            continue
        prop_type: Callable = str2bool if type(value) is bool else type(value)  # type: ignore
        parser.add_argument(f"--{prop_name}", type=prop_type, dest=prop_name)

    for key, value in vars(parser.parse_args()).items():
        if value is not None:
            flattened_props[key] = value

    return unflatten_properties(flattened_props)


def flatten_properties(config: Dict) -> Dict:
    properties = {}
    for key, value in config.items():
        if type(value) is dict:
            for key_2, value_2 in flatten_properties(value).items():
                properties[key + "." + key_2] = value_2
        else:
            properties[key] = value
    return properties


def unflatten_properties(config: Dict) -> Dict:
    properties: Dict = {}
    for key, value in config.items():
        if "." in key:
            add_property(properties, key, value)
        else:
            properties[key] = value
    return properties


def add_property(d: Dict, partial_key: str, value: Any):
    key_1, key_2 = partial_key.split(".", maxsplit=1)
    if key_1 not in d:
        d[key_1] = {}
    if "." in key_2:
        add_property(d[key_1], key_2, value)
    else:
        d[key_1][key_2] = value


def str2bool(v: Union[str, bool]) -> bool:
    # Source from https://stackoverflow.com/questions/15008758/parsing-boolean-values-with-argparse
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "True", "t", "y", "1"):
        return True
    elif v.lower() in ("no", "false", "False", "f", "n", "0"):
        return False
    else:
        raise argparse.ArgumentTypeError("Boolean value expected.")


def traverse_dict(d: Dict, key_path: str) -> Any:
    """
    Traverse nested dictionaries to find the element pointed-to by key_path.
    Key path components are separated by a ':' e.g.
      "root:child:a"
    """
    if type(d) is not dict:
        raise TypeError(f"unable to traverse into non-dict value with key path: {key_path}")

    # Extract one path component at a time
    components = key_path.split(":", maxsplit=1)
    if components is None or len(components) == 0:
        raise KeyError(f"invalid config key path: {key_path}")

    key = components[0]
    remaining_key_path = components[1] if len(components) > 1 else None

    val: Any = d.get(key, None)
    if val is not None:
        if remaining_key_path is not None:
            return traverse_dict(val, remaining_key_path)
        return val
    else:
        raise KeyError(f"value not found for key: {key}")


start_methods: Dict[str, Optional[Literal["fork", "forkserver", "spawn"]]] = {
    "default": None,
    "fork": "fork",
    "forkserver": "forkserver",
    "spawn": "spawn",
}


def process_config_start_method(
    config: Dict[str, Any],
    log=logging.Logger,
) -> Optional[Literal["fork", "forkserver", "spawn"]]:
    from_config = config.get("multiprocessing_start_method")

    # handle not only the key being missing, but also set to None
    if from_config is None:
        from_config = "default"

    processed_method = start_methods[from_config]

    if processed_method is None:
        start_methods_string = ", ".join(option for option in start_methods.keys())
        log.warning(
            f"Using default multiprocessing start method, configured start method {from_config!r} not available in:"
            f" {start_methods_string}"
        )
        return None

    log.info(f"Chosen multiprocessing start method: {processed_method}")

    return processed_method
