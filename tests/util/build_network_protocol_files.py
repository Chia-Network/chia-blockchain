import os
from pathlib import Path
from chia.util.streamable import Streamable, streamable
from tests.util.network_protocol_data import (
    new_signage_point, 
    declare_proof_of_space,
    request_signed_values,
    farming_info,
    signed_values,
    new_peak,
    new_transaction,
    request_transaction,
    respond_transaction,
    request_proof_of_weight,
    respond_proof_of_weight,
    request_block,
    reject_block,
    request_blocks,
    respond_blocks,
    reject_blocks,
    respond_block,
    new_unfinished_block,
    request_unfinished_block,
    respond_unfinished_block,
    new_signage_point_or_end_of_subslot,
    request_signage_point_or_end_of_subslot,
    respond_signage_point,
    respond_end_of_subslot,
    request_mempool_transaction,
    new_compact_vdf,
    request_compact_vdf,
    respond_compact_vdf,
    request_peers,
    respond_peers,
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


def get_full_node_bytes() -> bytes:
    result = b""
    result += encode_data(new_peak)
    result += encode_data(new_transaction)
    result += encode_data(request_transaction)
    result += encode_data(respond_transaction)
    result += encode_data(request_proof_of_weight)
    result += encode_data(respond_proof_of_weight)
    result += encode_data(request_block)
    result += encode_data(reject_block)
    result += encode_data(request_blocks)
    result += encode_data(respond_blocks)
    result += encode_data(reject_blocks)
    result += encode_data(respond_block)
    result += encode_data(new_unfinished_block)
    result += encode_data(request_unfinished_block)
    result += encode_data(respond_unfinished_block)
    result += encode_data(new_signage_point_or_end_of_subslot)
    result += encode_data(request_signage_point_or_end_of_subslot)
    result += encode_data(respond_signage_point)
    result += encode_data(respond_end_of_subslot)
    result += encode_data(request_mempool_transaction)
    result += encode_data(new_compact_vdf)
    result += encode_data(request_compact_vdf)
    result += encode_data(respond_compact_vdf)
    result += encode_data(request_peers)
    result += encode_data(respond_peers)
    return result


def get_protocol_bytes() -> bytes:
    return get_farmer_protocol_bytes() + get_full_node_bytes()


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
