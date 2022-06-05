import json
import os
import subprocess
import sysconfig
from typing import Callable, Any
from pathlib import Path

from tests.util.network_protocol_data import name_to_instance

version = "1.0"


tests_dir = Path(__file__).resolve().parent


def get_network_protocol_filename() -> Path:
    return tests_dir / Path(f"protocol_messages_bytes-v{version}.json")


def visit_all_messages(visitor: Callable[[Any, str], None]) -> None:
    for name, instance in name_to_instance.items():
        visitor(instance, name)


def get_protocol_bytes() -> str:

    result = {}

    def visitor(obj: Any, name: str) -> None:
        nonlocal result
        result[name] = bytes(obj).hex()

    visit_all_messages(visitor)

    return json.dumps(result, indent=4) + "\n"


def get_protocol_json() -> str:
    elements = {}

    def visitor(obj: Any, name: str) -> None:
        elements[name] = obj.to_json_dict()

    visit_all_messages(visitor)

    return json.dumps(elements, indent=4) + "\n"


if __name__ == "__main__":
    name_to_function = {
        os.fspath(get_network_protocol_filename()): get_protocol_bytes,
        "network_protocol_messages.json": get_protocol_json,
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
