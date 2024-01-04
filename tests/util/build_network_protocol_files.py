from __future__ import annotations

import os
import subprocess
import sysconfig
from pathlib import Path
from typing import Any, Callable

from chia.util.ints import uint32
from tests.util.network_protocol_data import *  # noqa: F403

version = "1.0"


tests_dir = Path(__file__).resolve().parent


def get_network_protocol_filename() -> Path:
    return tests_dir / Path("protocol_messages_bytes-v" + version)


def encode_data(data: Any) -> bytes:
    data_bytes = bytes(data)
    size = uint32(len(data_bytes))
    return size.to_bytes(4, "big") + data_bytes


def visit_farmer_protocol(visitor: Callable[[Any, str], None]) -> None:
    visitor(new_signage_point, "new_signage_point")
    visitor(declare_proof_of_space, "declare_proof_of_space")
    visitor(request_signed_values, "request_signed_values")
    visitor(farming_info, "farming_info")
    visitor(signed_values, "signed_values")


def visit_full_node(visitor: Callable[[Any, str], None]) -> None:
    visitor(new_peak, "new_peak")
    visitor(new_transaction, "new_transaction")
    visitor(request_transaction, "request_transaction")
    visitor(respond_transaction, "respond_transaction")
    visitor(request_proof_of_weight, "request_proof_of_weight")
    visitor(respond_proof_of_weight, "respond_proof_of_weight")
    visitor(request_block, "request_block")
    visitor(reject_block, "reject_block")
    visitor(request_blocks, "request_blocks")
    visitor(respond_blocks, "respond_blocks")
    visitor(reject_blocks, "reject_blocks")
    visitor(respond_block, "respond_block")
    visitor(new_unfinished_block, "new_unfinished_block")
    visitor(request_unfinished_block, "request_unfinished_block")
    visitor(respond_unfinished_block, "respond_unfinished_block")
    visitor(new_signage_point_or_end_of_subslot, "new_signage_point_or_end_of_subslot")
    visitor(request_signage_point_or_end_of_subslot, "request_signage_point_or_end_of_subslot")
    visitor(respond_signage_point, "respond_signage_point")
    visitor(respond_end_of_subslot, "respond_end_of_subslot")
    visitor(request_mempool_transaction, "request_mempool_transaction")
    visitor(new_compact_vdf, "new_compact_vdf")
    visitor(request_compact_vdf, "request_compact_vdf")
    visitor(respond_compact_vdf, "respond_compact_vdf")
    visitor(request_peers, "request_peers")
    visitor(respond_peers, "respond_peers")
    visitor(new_unfinished_block2, "new_unfinished_block2")
    visitor(request_unfinished_block2, "request_unfinished_block2")


def visit_wallet_protocol(visitor: Callable[[Any, str], None]) -> None:
    visitor(request_puzzle_solution, "request_puzzle_solution")
    visitor(puzzle_solution_response, "puzzle_solution_response")
    visitor(respond_puzzle_solution, "respond_puzzle_solution")
    visitor(reject_puzzle_solution, "reject_puzzle_solution")
    visitor(send_transaction, "send_transaction")
    visitor(transaction_ack, "transaction_ack")
    visitor(new_peak_wallet, "new_peak_wallet")
    visitor(request_block_header, "request_block_header")
    visitor(request_block_headers, "request_block_headers")
    visitor(respond_header_block, "respond_header_block")
    visitor(respond_block_headers, "respond_block_headers")
    visitor(reject_header_request, "reject_header_request")
    visitor(request_removals, "request_removals")
    visitor(respond_removals, "respond_removals")
    visitor(reject_removals_request, "reject_removals_request")
    visitor(request_additions, "request_additions")
    visitor(respond_additions, "respond_additions")
    visitor(reject_additions, "reject_additions")
    visitor(request_header_blocks, "request_header_blocks")
    visitor(reject_header_blocks, "reject_header_blocks")
    visitor(respond_header_blocks, "respond_header_blocks")
    visitor(coin_state, "coin_state")
    visitor(register_for_ph_updates, "register_for_ph_updates")
    visitor(reject_block_headers, "reject_block_headers"),
    visitor(respond_to_ph_updates, "respond_to_ph_updates")
    visitor(register_for_coin_updates, "register_for_coin_updates")
    visitor(respond_to_coin_updates, "respond_to_coin_updates")
    visitor(coin_state_update, "coin_state_update")
    visitor(request_children, "request_children")
    visitor(respond_children, "respond_children")
    visitor(request_ses_info, "request_ses_info")
    visitor(respond_ses_info, "respond_ses_info")


def visit_harvester_protocol(visitor: Callable[[Any, str], None]) -> None:
    visitor(pool_difficulty, "pool_difficulty")
    visitor(harvester_handhsake, "harvester_handhsake")
    visitor(new_signage_point_harvester, "new_signage_point_harvester")
    visitor(new_proof_of_space, "new_proof_of_space")
    visitor(request_signatures, "request_signatures")
    visitor(respond_signatures, "respond_signatures")
    visitor(plot, "plot")
    visitor(request_plots, "request_plots")
    visitor(respond_plots, "respond_plots")


def visit_introducer_protocol(visitor: Callable[[Any, str], None]) -> None:
    visitor(request_peers_introducer, "request_peers_introducer")
    visitor(respond_peers_introducer, "respond_peers_introducer")


def visit_pool_protocol(visitor: Callable[[Any, str], None]) -> None:
    visitor(authentication_payload, "authentication_payload")
    visitor(get_pool_info_response, "get_pool_info_response")
    visitor(post_partial_payload, "post_partial_payload")
    visitor(post_partial_request, "post_partial_request")
    visitor(post_partial_response, "post_partial_response")
    visitor(get_farmer_response, "get_farmer_response")
    visitor(post_farmer_payload, "post_farmer_payload")
    visitor(post_farmer_request, "post_farmer_request")
    visitor(post_farmer_response, "post_farmer_response")
    visitor(put_farmer_payload, "put_farmer_payload")
    visitor(put_farmer_request, "put_farmer_request")
    visitor(put_farmer_response, "put_farmer_response")
    visitor(error_response, "error_response")


def visit_timelord_protocol(visitor: Callable[[Any, str], None]) -> None:
    visitor(new_peak_timelord, "new_peak_timelord")
    visitor(new_unfinished_block_timelord, "new_unfinished_block_timelord")
    visitor(new_infusion_point_vdf, "new_infusion_point_vdf")
    visitor(new_signage_point_vdf, "new_signage_point_vdf")
    visitor(new_end_of_sub_slot_bundle, "new_end_of_sub_slot_bundle")
    visitor(request_compact_proof_of_time, "request_compact_proof_of_time")
    visitor(respond_compact_proof_of_time, "respond_compact_proof_of_time")


def visit_shared_protocol(visitor: Callable[[Any, str], None]) -> None:
    visitor(error_without_data, "error_without_data")
    visitor(error_with_data, "error_with_data")


def visit_all_messages(visitor: Callable[[Any, str], None]) -> None:
    visit_farmer_protocol(visitor)
    visit_full_node(visitor)
    visit_wallet_protocol(visitor)
    visit_harvester_protocol(visitor)
    visit_introducer_protocol(visitor)
    visit_pool_protocol(visitor)
    visit_timelord_protocol(visitor)
    visit_shared_protocol(visitor)


def get_protocol_bytes() -> bytes:
    result = b""

    def visitor(obj: Any, name: str) -> None:
        nonlocal result
        result += encode_data(obj)

    visit_all_messages(visitor)

    return result


def build_protocol_test() -> str:
    result = """# this file is generated by build_network_protocol_files.py

from __future__ import annotations

from pathlib import Path
from typing import Tuple

from tests.util.build_network_protocol_files import get_network_protocol_filename
from tests.util.network_protocol_data import *  # noqa: F403
from tests.util.protocol_messages_json import *  # noqa: F403


def parse_blob(input_bytes: bytes) -> Tuple[bytes, bytes]:
    size_bytes = input_bytes[:4]
    input_bytes = input_bytes[4:]
    size = int.from_bytes(size_bytes, "big")
    message_bytes = input_bytes[:size]
    input_bytes = input_bytes[size:]
    return (message_bytes, input_bytes)


def test_protocol_bytes() -> None:

    filename: Path = get_network_protocol_filename()
    assert filename.exists()
    with open(filename, "rb") as f:
        input_bytes = f.read()

"""

    counter = 0

    def visitor(obj: Any, name: str) -> None:
        nonlocal result
        nonlocal counter
        result += f"""    message_bytes, input_bytes = parse_blob(input_bytes)
    message_{counter} = type({name}).from_bytes(message_bytes)
    assert message_{counter} == {name}
    assert bytes(message_{counter}) == bytes({name})

"""
        counter += 1

    visit_all_messages(visitor)

    result += '    assert input_bytes == b""\n'
    return result


def get_protocol_json() -> str:
    result = """# this file is generated by build_network_protocol_files.py
from __future__ import annotations

from typing import Any, Dict
"""
    counter = 0

    def visitor(obj: Any, name: str) -> None:
        nonlocal result
        nonlocal counter
        result += f"\n{name}_json: Dict[str, Any] = {obj.to_json_dict()}\n"
        counter += 1

    visit_all_messages(visitor)

    return result


def build_json_test() -> str:
    result = """# this file is generated by build_network_protocol_files.py

from __future__ import annotations

from tests.util.network_protocol_data import *  # noqa: F403
from tests.util.protocol_messages_json import *  # noqa: F403


def test_protocol_json() -> None:
"""
    counter = 0

    def visitor(obj: Any, name: str) -> None:
        nonlocal result
        nonlocal counter
        result += f"    assert str({name}_json) == str({name}.to_json_dict())\n"
        result += f"    assert type({name}).from_json_dict({name}_json) == {name}\n"
        counter += 1

    visit_all_messages(visitor)

    return result


def main() -> None:
    get_network_protocol_filename().write_bytes(get_protocol_bytes())

    name_to_function = {
        "test_network_protocol_files.py": build_protocol_test,
        "protocol_messages_json.py": get_protocol_json,
        "test_network_protocol_json.py": build_json_test,
    }

    scripts_path = Path(sysconfig.get_path("scripts"))

    for name, function in name_to_function.items():
        path = tests_dir.joinpath(name)
        path.write_text(function())
        # black seems to have trouble when run as a module so not using `python -m black`
        subprocess.run(
            [scripts_path.joinpath("black"), os.fspath(path.relative_to(tests_dir))],
            check=True,
            cwd=tests_dir,
        )


if __name__ == "__main__":
    main()
