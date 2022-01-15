# flake8: noqa

import os
from pathlib import Path
from chinilla.util.streamable import Streamable, streamable
from tests.util.network_protocol_data import *
from chinilla.util.ints import uint32

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


def get_wallet_protocol_bytes() -> bytes:
    result = b""
    result += encode_data(request_puzzle_solution)
    result += encode_data(puzzle_solution_response)
    result += encode_data(respond_puzzle_solution)
    result += encode_data(reject_puzzle_solution)
    result += encode_data(send_transaction)
    result += encode_data(transaction_ack)
    result += encode_data(new_peak_wallet)
    result += encode_data(request_block_header)
    result += encode_data(respond_header_block)
    result += encode_data(reject_header_request)
    result += encode_data(request_removals)
    result += encode_data(respond_removals)
    result += encode_data(reject_removals_request)
    result += encode_data(request_additions)
    result += encode_data(respond_additions)
    result += encode_data(reject_additions)
    result += encode_data(request_header_blocks)
    result += encode_data(reject_header_blocks)
    result += encode_data(respond_header_blocks)
    result += encode_data(coin_state)
    result += encode_data(register_for_ph_updates)
    result += encode_data(respond_to_ph_updates)
    result += encode_data(register_for_coin_updates)
    result += encode_data(respond_to_coin_updates)
    result += encode_data(coin_state_update)
    result += encode_data(request_children)
    result += encode_data(respond_children)
    result += encode_data(request_ses_info)
    result += encode_data(respond_ses_info)
    return result


def get_harvester_protocol_bytes() -> bytes:
    result = b""
    result += encode_data(pool_difficulty)
    result += encode_data(harvester_handhsake)
    result += encode_data(new_signage_point_harvester)
    result += encode_data(new_proof_of_space)
    result += encode_data(request_signatures)
    result += encode_data(respond_signatures)
    result += encode_data(plot)
    result += encode_data(request_plots)
    result += encode_data(respond_plots)
    return result


def get_introducer_protocol_bytes() -> bytes:
    result = b""
    result += encode_data(request_peers_introducer)
    result += encode_data(respond_peers_introducer)
    return result


def get_pool_protocol_bytes() -> bytes:
    result = b""
    result += encode_data(authentication_payload)
    result += encode_data(get_pool_info_response)
    result += encode_data(post_partial_payload)
    result += encode_data(post_partial_request)
    result += encode_data(post_partial_response)
    result += encode_data(get_farmer_response)
    result += encode_data(post_farmer_payload)
    result += encode_data(post_farmer_request)
    result += encode_data(post_farmer_response)
    result += encode_data(put_farmer_payload)
    result += encode_data(put_farmer_request)
    result += encode_data(put_farmer_response)
    result += encode_data(error_response)
    return result


def get_timelord_protocol_bytes() -> bytes:
    result = b""
    result += encode_data(new_peak_timelord)
    result += encode_data(new_unfinished_block_timelord)
    result += encode_data(new_infusion_point_vdf)
    result += encode_data(new_signage_point_vdf)
    result += encode_data(new_end_of_sub_slot_bundle)
    result += encode_data(request_compact_proof_of_time)
    result += encode_data(respond_compact_proof_of_time)
    return result


def get_protocol_bytes() -> bytes:
    return (
        get_farmer_protocol_bytes()
        + get_full_node_bytes()
        + get_wallet_protocol_bytes()
        + get_harvester_protocol_bytes()
        + get_introducer_protocol_bytes()
        + get_pool_protocol_bytes()
        + get_timelord_protocol_bytes()
    )


if __name__ == "__main__":
    filename = get_network_protocol_filename()
    data = get_protocol_bytes()
    if os.path.exists(filename):
        print("Deleting old file.")
        os.remove(filename)
    f = open(filename, "wb")
    f.write(data)
    f.close()
    print(f"Written {len(data)} bytes.")
