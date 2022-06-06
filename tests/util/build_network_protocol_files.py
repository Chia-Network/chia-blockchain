import json
import os
import subprocess
import sysconfig
from typing import Any, Callable, Dict
from pathlib import Path

from typing_extensions import TypedDict

from chia.util.streamable import Streamable
from tests.util.network_protocol_data import module_to_name_to_instance

version = "1.0"


tests_dir = Path(__file__).resolve().parent


class MessageDict(TypedDict):
    bytes: str
    json: Dict[str, Any]


SerializedProtocolData = Dict[str, Dict[str, MessageDict]]


def get_network_protocol_filename() -> Path:
    return tests_dir / Path(f"protocol_messages_bytes-v{version}.json")


def visit_all_messages(visitor: Callable[[Streamable, str], None]) -> None:
    for module, name_to_instance in module_to_name_to_instance.items():
        for name, instance in name_to_instance.items():
            visitor(instance, name)


def get_protocol_data() -> str:
    hexed: SerializedProtocolData = {
        module: {
            name: {"bytes": bytes(instance).hex(), "json": instance.to_json_dict()}
            for name, instance in name_to_instance.items()
        }
        for module, name_to_instance in module_to_name_to_instance.items()
    }

    return json.dumps(hexed, indent=4) + "\n"


if __name__ == "__main__":
    name_to_function = {
        os.fspath(get_network_protocol_filename()): get_protocol_data,
    }

    scripts_path = Path(sysconfig.get_path("scripts"))

    for name, function in name_to_function.items():
        path = tests_dir.joinpath(name)
        path.write_text(function())
        if path.suffix == ".py":
            # black seems to have trouble when run as a module so not using `python -m black`
            subprocess.run(
                [scripts_path.joinpath("black"), os.fspath(path.relative_to(tests_dir))],
                check=True,
                cwd=tests_dir,
            )
