import json
import sys
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


def main():
    get_network_protocol_filename().write_text(get_protocol_data())


if __name__ == "__main__":
    sys.exit(main())
