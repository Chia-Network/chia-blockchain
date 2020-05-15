import argparse
import pkg_resources
import sys
import yaml

from pathlib import Path
from typing import Dict, Any, Callable, Optional, Union
from src.util.path import mkdir


def initial_config_file(filename: Union[str, Path]) -> str:
    return pkg_resources.resource_string(__name__, f"initial-{filename}").decode()


def create_default_chia_config(root_path: Path) -> None:
    for filename in ["config.yaml"]:
        default_config_file_data = initial_config_file(filename)
        path = config_path_for_filename(root_path, filename)
        mkdir(path.parent)
        with open(path, "w") as f:
            f.write(default_config_file_data)
    plot_yaml_path: Path = root_path / "config" / "plots.yaml"
    if not plot_yaml_path.exists():
        save_config(root_path, "plots.yaml", {"plots": {}})


def config_path_for_filename(root_path: Path, filename: Union[str, Path]) -> Path:
    path_filename = Path(filename)
    if path_filename.is_absolute():
        return path_filename
    return root_path / "config" / filename


def save_config(root_path: Path, filename: Union[str, Path], config_data: Any):
    path = config_path_for_filename(root_path, filename)
    with open(path, "w") as f:
        yaml.safe_dump(config_data, f)


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


def load_config_cli(root_path: Path, filename: str, sub_config: Optional[str]) -> Dict:
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
    key_1, key_2 = partial_key.split(".", maxsplit=1)
    if key_1 not in d:
        d[key_1] = {}
    if "." in key_2:
        add_property(d[key_1], key_2, value)
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
