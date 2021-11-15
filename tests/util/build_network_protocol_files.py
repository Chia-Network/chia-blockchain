import os
from pathlib import Path
from chia.util.streamable import Streamable, streamable
from tests.util.network_protocol_data import (
    new_signage_point, 
    declare_proof_of_space,
    request_signed_values,
    farming_info,
    signed_values,
)
from chia.util.ints import uint32

version = "1.0"


def get_network_protocol_filename() -> Path:
    tests_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    return tests_dir / Path("protocol_messages_bytes-v" + version)


def encode_data(data) -> bytes:
    data_bytes = bytes(data)
    size = uint32(len(data_bytes))
    return size.to_bytes(4, "big") + data_bytes


def get_farmer_protocol_bytes() -> bytes:
    result = b""
    result += encode_data(new_signage_point)
    result += encode_data(declare_proof_of_space)
    result += encode_data(request_signed_values)
    result += encode_data(farming_info)
    result += encode_data(signed_values)
    return result


def get_protocol_bytes() -> bytes:
    return get_farmer_protocol_bytes()


if __name__ == "__main__":
    filename = get_network_protocol_filename()
    data = get_protocol_bytes()
    if os.path.exists(filename):
        print("Deleting old file.")
        os.remove(filename)
    f = open(filename, 'wb')
    f.write(data)
    f.close()
    print(f"Written {len(data)} bytes.")
