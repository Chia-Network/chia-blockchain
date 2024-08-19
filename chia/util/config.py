from __future__ import annotations

import argparse
import contextlib
import copy
import logging
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Union, cast

import importlib_resources
import yaml
from typing_extensions import Literal

from chia.server.outbound_message import NodeType
from chia.types.peer_info import UnresolvedPeerInfo
from chia.util.lock import Lockfile

log = logging.getLogger(__name__)


def initial_config_file(filename: Union[str, Path]) -> str:
    initial_config_path = importlib_resources.files(__name__.rpartition(".")[0]).joinpath(f"initial-{filename}")
    contents: str = initial_config_path.read_text(encoding="utf-8")
    return contents


def create_default_chia_config(root_path: Path, filenames: List[str] = ["config.yaml"]) -> None:
    for filename in filenames:
        default_config_file_data: str = initial_config_file(filename)
        path: Path = config_path_for_filename(root_path, filename)
        tmp_path: Path = path.with_suffix("." + str(os.getpid()))
        path.parent.mkdir(parents=True, exist_ok=True)
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


@contextlib.contextmanager
def lock_config(root_path: Path, filename: Union[str, Path]) -> Iterator[None]:
    # TODO: This is presently used in some tests to lock the saving of the
    #       configuration file without having loaded it right there.  This usage
    #       should probably be removed and this function made private.
    config_path = config_path_for_filename(root_path, filename)
    with Lockfile.create(config_path):
        yield


@contextlib.contextmanager
def lock_and_load_config(
    root_path: Path,
    filename: Union[str, Path],
    fill_missing_services: bool = False,
) -> Iterator[Dict[str, Any]]:
    with lock_config(root_path=root_path, filename=filename):
        config = _load_config_maybe_locked(
            root_path=root_path,
            filename=filename,
            acquire_lock=False,
            fill_missing_services=fill_missing_services,
        )
        yield config


def save_config(root_path: Path, filename: Union[str, Path], config_data: Any) -> None:
    # This must be called under an acquired config lock
    path: Path = config_path_for_filename(root_path, filename)
    with tempfile.TemporaryDirectory(dir=path.parent) as tmp_dir:
        tmp_path: Path = Path(tmp_dir) / Path(filename)
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
    exit_on_error: bool = True,
    fill_missing_services: bool = False,
) -> Dict[str, Any]:
    return _load_config_maybe_locked(
        root_path=root_path,
        filename=filename,
        sub_config=sub_config,
        exit_on_error=exit_on_error,
        acquire_lock=True,
        fill_missing_services=fill_missing_services,
    )


def _load_config_maybe_locked(
    root_path: Path,
    filename: Union[str, Path],
    sub_config: Optional[str] = None,
    exit_on_error: bool = True,
    acquire_lock: bool = True,
    fill_missing_services: bool = False,
) -> Dict[str, Any]:
    # This must be called under an acquired config lock, or acquire_lock should be True

    path = config_path_for_filename(root_path, filename)

    if not path.is_file():
        if not exit_on_error:
            raise ValueError("Config not found")
        print(f"can't find {path}")
        print("** please run `chia init` to migrate or create new config files **")
        # TODO: fix this hack
        sys.exit(-1)
    # This loop should not be necessary due to the config lock, but it's kept here just in case
    for i in range(10):
        try:
            # at least we intend it to be this type
            r: Dict[str, Any]
            with contextlib.ExitStack() as exit_stack:
                if acquire_lock:
                    exit_stack.enter_context(lock_config(root_path, filename))
                with open(path) as opened_config_file:
                    r = yaml.safe_load(opened_config_file)
            if r is None:
                log.error(f"yaml.safe_load returned None: {path}")
                time.sleep(i * 0.1)
                continue
            if fill_missing_services:
                r.update(load_defaults_for_missing_services(config=r, config_name=path.name))
            if sub_config is not None:
                r = cast(Dict[str, Any], r.get(sub_config))
            return r
        except Exception as e:
            tb = traceback.format_exc()
            log.error(f"Error loading file: {tb} {e} Retrying {i}")
            time.sleep(i * 0.1)
    raise RuntimeError("Was not able to read config file successfully")


def load_config_cli(
    root_path: Path,
    filename: str,
    sub_config: Optional[str] = None,
    fill_missing_services: bool = False,
) -> Dict[str, Any]:
    """
    Loads configuration from the specified filename, in the config directory,
    and then overrides any properties using the passed in command line arguments.
    Nested properties in the config file can be used in the command line with ".",
    for example --farmer_peer.host. Does not support lists.
    """
    config = load_config(root_path, filename, sub_config, fill_missing_services=fill_missing_services)

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


def flatten_properties(config: Dict[str, Any]) -> Dict[str, Any]:
    properties = {}
    for key, value in config.items():
        if type(value) is dict:
            for key_2, value_2 in flatten_properties(value).items():
                properties[key + "." + key_2] = value_2
        else:
            properties[key] = value
    return properties


def unflatten_properties(config: Dict[str, Any]) -> Dict[str, Any]:
    properties: Dict[str, Any] = {}
    for key, value in config.items():
        if "." in key:
            add_property(properties, key, value)
        else:
            properties[key] = value
    return properties


def add_property(d: Dict[str, Any], partial_key: str, value: Any) -> None:
    if "." not in partial_key:  # root of dict
        d[partial_key] = value
    else:
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


def traverse_dict(d: Dict[str, Any], key_path: str) -> Any:
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


method_strings = Literal["default", "python_default", "fork", "forkserver", "spawn"]
method_values = Optional[Literal["fork", "forkserver", "spawn"]]
start_methods: Dict[method_strings, method_values] = {
    "default": None,
    "python_default": None,
    "fork": "fork",
    "forkserver": "forkserver",
    "spawn": "spawn",
}


def process_config_start_method(
    config: Dict[str, Any],
    log: logging.Logger,
) -> method_values:
    from_config: object = config.get("multiprocessing_start_method")

    choice: method_strings
    if from_config is None:
        # handle not only the key being missing, but also set to None
        choice = "default"
    elif from_config not in start_methods.keys():
        start_methods_string = ", ".join(option for option in start_methods.keys())
        log.warning(f"Configured start method {from_config!r} not available in: {start_methods_string}")
        choice = "default"
    else:
        # mypy doesn't realize that by the time we get here from_config must be one of
        # the keys in `start_methods` due to the above `not in` condition.
        choice = from_config  # type: ignore[assignment]

    processed_method = start_methods[choice]
    log.info(f"Selected multiprocessing start method: {choice}")

    return processed_method


def override_config(config: Dict[str, Any], config_overrides: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    new_config = copy.deepcopy(config)
    if config_overrides is None:
        return new_config
    for k, v in config_overrides.items():
        add_property(new_config, k, v)
    return new_config


def selected_network_address_prefix(config: Dict[str, Any]) -> str:
    # we intend this to be a str at least
    address_prefix: str = config["network_overrides"]["config"][config["selected_network"]]["address_prefix"]
    return address_prefix


def load_defaults_for_missing_services(config: Dict[str, Any], config_name: str) -> Dict[str, Any]:
    services = ["data_layer"]
    missing_services = [service for service in services if service not in config]
    defaulted = {}
    if len(missing_services) > 0:
        marshalled_default_config: str = initial_config_file(config_name)

        unmarshalled_default_config = yaml.safe_load(marshalled_default_config)

        for service in missing_services:
            defaulted[service] = unmarshalled_default_config[service]

            if "logging" in defaulted[service]:
                to_be_referenced = config.get("logging")
                if to_be_referenced is not None:
                    defaulted[service]["logging"] = to_be_referenced

            if "selected_network" in defaulted[service]:
                to_be_referenced = config.get("selected_network")
                if to_be_referenced is not None:
                    # joining to hopefully force a new string of the same value
                    defaulted[service]["selected_network"] = "".join(to_be_referenced)

    return defaulted


PEER_INFO_MAPPING: Dict[NodeType, str] = {
    NodeType.FULL_NODE: "full_node_peer",
    NodeType.FARMER: "farmer_peer",
}


def get_unresolved_peer_infos(service_config: Dict[str, Any], peer_type: NodeType) -> Set[UnresolvedPeerInfo]:
    peer_info_key = PEER_INFO_MAPPING[peer_type]
    peer_infos: List[Dict[str, Any]] = service_config.get(f"{peer_info_key}s", [])
    peer_info: Optional[Dict[str, Any]] = service_config.get(peer_info_key)
    if peer_info is not None:
        peer_infos.append(peer_info)

    return {UnresolvedPeerInfo(host=peer["host"], port=peer["port"]) for peer in peer_infos}


def set_peer_info(
    service_config: Dict[str, Any],
    peer_type: NodeType,
    peer_host: Optional[str] = None,
    peer_port: Optional[int] = None,
) -> None:
    peer_info_key = PEER_INFO_MAPPING[peer_type]
    if peer_info_key in service_config:
        if peer_host is not None:
            service_config[peer_info_key]["host"] = peer_host
        if peer_port is not None:
            service_config[peer_info_key]["port"] = peer_port
    elif f"{peer_info_key}s" in service_config and len(service_config[f"{peer_info_key}s"]) > 0:
        if peer_host is not None:
            service_config[f"{peer_info_key}s"][0]["host"] = peer_host
        if peer_port is not None:
            service_config[f"{peer_info_key}s"][0]["port"] = peer_port
