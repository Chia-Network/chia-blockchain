# flake8: noqa

import os
from typing import Callable, Any
from pathlib import Path
from chia.util.streamable import Streamable, streamable
from tests.util.network_protocol_data import *
from chia.util.ints import uint32

version = "1.0"


def get_network_protocol_filename() -> Path:
    tests_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    return tests_dir / Path("protocol_messages_bytes-v" + version)


def encode_data(data) -> bytes:
    data_bytes = bytes(data)
    size = uint32(len(data_bytes))
    return size.to_bytes(4, "big") + data_bytes


def visit_farmer_protocol(visitor: Callable[[Any], None]) -> None:
    visitor(new_signage_point)
    visitor(declare_proof_of_space)
    visitor(request_signed_values)
    visitor(farming_info)
    visitor(signed_values)


def visit_full_node(visitor: Callable[[Any], None]) -> None:
    visitor(new_peak)
    visitor(new_transaction)
    visitor(request_transaction)
    visitor(respond_transaction)
    visitor(request_proof_of_weight)
    visitor(respond_proof_of_weight)
    visitor(request_block)
    visitor(reject_block)
    visitor(request_blocks)
    visitor(respond_blocks)
    visitor(reject_blocks)
    visitor(respond_block)
    visitor(new_unfinished_block)
    visitor(request_unfinished_block)
    visitor(respond_unfinished_block)
    visitor(new_signage_point_or_end_of_subslot)
    visitor(request_signage_point_or_end_of_subslot)
    visitor(respond_signage_point)
    visitor(respond_end_of_subslot)
    visitor(request_mempool_transaction)
    visitor(new_compact_vdf)
    visitor(request_compact_vdf)
    visitor(respond_compact_vdf)
    visitor(request_peers)
    visitor(respond_peers)


def visit_wallet_protocol(visitor: Callable[[Any], None]) -> None:
    visitor(request_puzzle_solution)
    visitor(puzzle_solution_response)
    visitor(respond_puzzle_solution)
    visitor(reject_puzzle_solution)
    visitor(send_transaction)
    visitor(transaction_ack)
    visitor(new_peak_wallet)
    visitor(request_block_header)
    visitor(respond_header_block)
    visitor(reject_header_request)
    visitor(request_removals)
    visitor(respond_removals)
    visitor(reject_removals_request)
    visitor(request_additions)
    visitor(respond_additions)
    visitor(reject_additions)
    visitor(request_header_blocks)
    visitor(reject_header_blocks)
    visitor(respond_header_blocks)
    visitor(coin_state)
    visitor(register_for_ph_updates)
    visitor(respond_to_ph_updates)
    visitor(register_for_coin_updates)
    visitor(respond_to_coin_updates)
    visitor(coin_state_update)
    visitor(request_children)
    visitor(respond_children)
    visitor(request_ses_info)
    visitor(respond_ses_info)


def visit_harvester_protocol(visitor: Callable[[Any], None]) -> None:
    visitor(pool_difficulty)
    visitor(harvester_handhsake)
    visitor(new_signage_point_harvester)
    visitor(new_proof_of_space)
    visitor(request_signatures)
    visitor(respond_signatures)
    visitor(plot)
    visitor(request_plots)
    visitor(respond_plots)


def visit_introducer_protocol(visitor: Callable[[Any], None]) -> None:
    visitor(request_peers_introducer)
    visitor(respond_peers_introducer)


def visit_pool_protocol(visitor: Callable[[Any], None]) -> None:
    visitor(authentication_payload)
    visitor(get_pool_info_response)
    visitor(post_partial_payload)
    visitor(post_partial_request)
    visitor(post_partial_response)
    visitor(get_farmer_response)
    visitor(post_farmer_payload)
    visitor(post_farmer_request)
    visitor(post_farmer_response)
    visitor(put_farmer_payload)
    visitor(put_farmer_request)
    visitor(put_farmer_response)
    visitor(error_response)


def visit_timelord_protocol(visitor: Callable[[Any], None]) -> None:
    visitor(new_peak_timelord)
    visitor(new_unfinished_block_timelord)
    visitor(new_infusion_point_vdf)
    visitor(new_signage_point_vdf)
    visitor(new_end_of_sub_slot_bundle)
    visitor(request_compact_proof_of_time)
    visitor(respond_compact_proof_of_time)


def visit_all_messages(visitor: Callable[[Any], None]) -> None:
    visit_farmer_protocol(visitor)
    visit_full_node(visitor)
    visit_wallet_protocol(visitor)
    visit_harvester_protocol(visitor)
    visit_introducer_protocol(visitor)
    visit_pool_protocol(visitor)
    visit_timelord_protocol(visitor)


def get_protocol_bytes() -> bytes:

    result = b""

    def visitor(obj: Any) -> None:
        nonlocal result
        result += encode_data(obj)

    visit_all_messages(visitor)

    return result


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
