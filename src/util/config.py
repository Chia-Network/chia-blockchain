import yaml
import argparse
import pathlib
import pkg_resources
from typing import Dict, Any, Callable, Optional
from src.definitions import ROOT_DIR


def migrate_config_file(filename: str, path: pathlib.Path) -> None:
    default_config_file = pkg_resources.resource_string(
        __name__, f"initial-{filename}"
    ).decode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(default_config_file)


def save_config(filename: str, config_data):
    path = ROOT_DIR / "config" / filename
    with open(path, "w") as f:
        yaml.safe_dump(config_data, f)


def load_config(filename: str, sub_config: Optional[str] = None) -> Dict:
    path = ROOT_DIR / "config" / filename
    if not path.is_file():
        migrate_config_file(filename, path)
    if sub_config is not None:
        return yaml.safe_load(open(path, "r"))[sub_config]
    else:
        return yaml.safe_load(open(path, "r"))


def load_config_cli(filename: str, sub_config: Optional[str] = None) -> Dict:
    """
    Loads configuration from the specified filename, in the config directory,
    and then overrides any properties using the passed in command line arguments.
    Nested properties in the config file can be used in the command line with ".",
    for example --farmer_peer.host. Does not support lists.
    """
    config = load_config(filename, sub_config)

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


def flatten_properties(config: Dict):
    properties = {}
    for key, value in config.items():
        if type(value) is dict:
            for key_2, value_2 in flatten_properties(value).items():
                properties[key + "." + key_2] = value_2
        else:
            properties[key] = value
    return properties


def unflatten_properties(config: Dict):
    properties: Dict = {}
    for key, value in config.items():
        if "." in key:
            add_property(properties, key, value)
        else:
            properties[key] = value
    return properties


def add_property(d: Dict, partial_key: str, value: Any):
    key_1, key_2 = partial_key.split(".")
    if key_1 not in d:
        d[key_1] = {}
    if "." in key_2:
        add_property(d, key_2, value)
    else:
        d[key_1][key_2] = value


def str2bool(v: Any) -> bool:
    # Source from https://stackoverflow.com/questions/15008758/parsing-boolean-values-with-argparse
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "True", "t", "y", "1"):
        return True
    elif v.lower() in ("no", "false", "False", "f", "n", "0"):
        return False
    else:
        raise argparse.ArgumentTypeError("Boolean value expected.")
