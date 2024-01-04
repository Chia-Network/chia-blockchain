# All of these rate limits scale with the number of transactions so the aggregate amounts are higher
from __future__ import annotations

import copy
import dataclasses
import functools
from typing import Any, Dict, List, Optional

from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import Capability

compose_rate_limits_cache: Dict[int, Dict[str, Any]] = {}


@dataclasses.dataclass(frozen=True)
class RLSettings:
    frequency: int  # Max request per time period (ie 1 min)
    max_size: int  # Max size of each request
    max_total_size: Optional[int] = None  # Max cumulative size of all requests in that period


def get_rate_limits_to_use(our_capabilities: List[Capability], peer_capabilities: List[Capability]) -> Dict[str, Any]:
    # This will use the newest possible rate limits that both peers support. At this time there are only two
    # options, v1 and v2.

    if Capability.RATE_LIMITS_V2 in our_capabilities and Capability.RATE_LIMITS_V2 in peer_capabilities:
        # Use V2 rate limits
        if 2 in compose_rate_limits_cache:
            return compose_rate_limits_cache[2]
        composed = compose_rate_limits(rate_limits[1], rate_limits[2])
        compose_rate_limits_cache[2] = composed
        return composed
    else:
        # Use V1 rate limits
        return rate_limits[1]


def compose_rate_limits(old_rate_limits: Dict[str, Any], new_rate_limits: Dict[str, Any]) -> Dict[str, Any]:
    # Composes two rate limits dicts, so that the newer values override the older values
    final_rate_limits: Dict[str, Any] = copy.deepcopy(new_rate_limits)
    categories: List[str] = ["rate_limits_tx", "rate_limits_other"]
    all_new_msgs_lists: List[List[ProtocolMessageTypes]] = [
        list(new_rate_limits[category].keys()) for category in categories
    ]
    all_new_msgs: List[ProtocolMessageTypes] = functools.reduce(lambda a, b: a + b, all_new_msgs_lists)
    for old_cat, mapping in old_rate_limits.items():
        if old_cat in categories:
            for old_protocol_msg, old_rate_limit_value in mapping.items():
                if old_protocol_msg not in all_new_msgs:
                    if old_cat not in final_rate_limits:
                        final_rate_limits[old_cat] = {}
                    final_rate_limits[old_cat][old_protocol_msg] = old_rate_limit_value
    return final_rate_limits


# Each number in this dict corresponds to a specific version of rate limits (1, 2,  etc).
# Version 1 includes the original limits for chia software from versions 1.0 to 1.4.
rate_limits = {
    1: {
        "default_settings": RLSettings(100, 1024 * 1024, 100 * 1024 * 1024),
        "non_tx_freq": 1000,  # There is also a freq limit for many requests
        "non_tx_max_total_size": 100 * 1024 * 1024,  # There is also a size limit for many requests
        # All transaction related apis also have an aggregate limit
        "rate_limits_tx": {
            ProtocolMessageTypes.new_transaction: RLSettings(5000, 100, 5000 * 100),
            ProtocolMessageTypes.request_transaction: RLSettings(5000, 100, 5000 * 100),
            ProtocolMessageTypes.respond_transaction: RLSettings(
                5000, 1 * 1024 * 1024, 20 * 1024 * 1024
            ),  # TODO: check this
            ProtocolMessageTypes.send_transaction: RLSettings(5000, 1024 * 1024),
            ProtocolMessageTypes.transaction_ack: RLSettings(5000, 2048),
        },
        # All non-transaction apis also have an aggregate limit
        "rate_limits_other": {
            ProtocolMessageTypes.handshake: RLSettings(5, 10 * 1024, 5 * 10 * 1024),
            ProtocolMessageTypes.harvester_handshake: RLSettings(5, 1024 * 1024),
            ProtocolMessageTypes.new_signage_point_harvester: RLSettings(100, 1024),
            ProtocolMessageTypes.new_proof_of_space: RLSettings(100, 2048),
            ProtocolMessageTypes.request_signatures: RLSettings(100, 2048),
            ProtocolMessageTypes.respond_signatures: RLSettings(100, 2048),
            ProtocolMessageTypes.new_signage_point: RLSettings(200, 2048),
            ProtocolMessageTypes.declare_proof_of_space: RLSettings(100, 10 * 1024),
            ProtocolMessageTypes.request_signed_values: RLSettings(100, 512),
            ProtocolMessageTypes.farming_info: RLSettings(100, 1024),
            ProtocolMessageTypes.signed_values: RLSettings(100, 1024),
            ProtocolMessageTypes.new_peak_timelord: RLSettings(100, 20 * 1024),
            ProtocolMessageTypes.new_unfinished_block_timelord: RLSettings(100, 10 * 1024),
            ProtocolMessageTypes.new_signage_point_vdf: RLSettings(100, 100 * 1024),
            ProtocolMessageTypes.new_infusion_point_vdf: RLSettings(100, 100 * 1024),
            ProtocolMessageTypes.new_end_of_sub_slot_vdf: RLSettings(100, 100 * 1024),
            ProtocolMessageTypes.request_compact_proof_of_time: RLSettings(100, 10 * 1024),
            ProtocolMessageTypes.respond_compact_proof_of_time: RLSettings(100, 100 * 1024),
            ProtocolMessageTypes.new_peak: RLSettings(200, 512),
            ProtocolMessageTypes.request_proof_of_weight: RLSettings(5, 100),
            ProtocolMessageTypes.respond_proof_of_weight: RLSettings(5, 50 * 1024 * 1024, 100 * 1024 * 1024),
            ProtocolMessageTypes.request_block: RLSettings(200, 100),
            ProtocolMessageTypes.reject_block: RLSettings(200, 100),
            ProtocolMessageTypes.request_blocks: RLSettings(500, 100),
            ProtocolMessageTypes.respond_blocks: RLSettings(100, 50 * 1024 * 1024, 5 * 50 * 1024 * 1024),
            ProtocolMessageTypes.reject_blocks: RLSettings(100, 100),
            ProtocolMessageTypes.respond_block: RLSettings(200, 2 * 1024 * 1024, 10 * 2 * 1024 * 1024),
            ProtocolMessageTypes.new_unfinished_block: RLSettings(200, 100),
            ProtocolMessageTypes.request_unfinished_block: RLSettings(200, 100),
            ProtocolMessageTypes.new_unfinished_block2: RLSettings(200, 100),
            ProtocolMessageTypes.request_unfinished_block2: RLSettings(200, 100),
            ProtocolMessageTypes.respond_unfinished_block: RLSettings(200, 2 * 1024 * 1024, 10 * 2 * 1024 * 1024),
            ProtocolMessageTypes.new_signage_point_or_end_of_sub_slot: RLSettings(200, 200),
            ProtocolMessageTypes.request_signage_point_or_end_of_sub_slot: RLSettings(200, 200),
            ProtocolMessageTypes.respond_signage_point: RLSettings(200, 50 * 1024),
            ProtocolMessageTypes.respond_end_of_sub_slot: RLSettings(100, 50 * 1024),
            ProtocolMessageTypes.request_mempool_transactions: RLSettings(5, 1024 * 1024),
            ProtocolMessageTypes.request_compact_vdf: RLSettings(200, 1024),
            ProtocolMessageTypes.respond_compact_vdf: RLSettings(200, 100 * 1024),
            ProtocolMessageTypes.new_compact_vdf: RLSettings(100, 1024),
            ProtocolMessageTypes.request_peers: RLSettings(10, 100),
            ProtocolMessageTypes.respond_peers: RLSettings(10, 1 * 1024 * 1024),
            ProtocolMessageTypes.request_puzzle_solution: RLSettings(1000, 100),
            ProtocolMessageTypes.respond_puzzle_solution: RLSettings(1000, 1024 * 1024),
            ProtocolMessageTypes.reject_puzzle_solution: RLSettings(1000, 100),
            ProtocolMessageTypes.new_peak_wallet: RLSettings(200, 300),
            ProtocolMessageTypes.request_block_header: RLSettings(500, 100),
            ProtocolMessageTypes.respond_block_header: RLSettings(500, 500 * 1024),
            ProtocolMessageTypes.reject_header_request: RLSettings(500, 100),
            ProtocolMessageTypes.request_removals: RLSettings(500, 50 * 1024, 10 * 1024 * 1024),
            ProtocolMessageTypes.respond_removals: RLSettings(500, 1024 * 1024, 10 * 1024 * 1024),
            ProtocolMessageTypes.reject_removals_request: RLSettings(500, 100),
            ProtocolMessageTypes.request_additions: RLSettings(500, 1024 * 1024, 10 * 1024 * 1024),
            ProtocolMessageTypes.respond_additions: RLSettings(500, 1024 * 1024, 10 * 1024 * 1024),
            ProtocolMessageTypes.reject_additions_request: RLSettings(500, 100),
            ProtocolMessageTypes.request_header_blocks: RLSettings(500, 100),
            ProtocolMessageTypes.reject_header_blocks: RLSettings(100, 100),
            ProtocolMessageTypes.respond_header_blocks: RLSettings(500, 2 * 1024 * 1024, 100 * 1024 * 1024),
            ProtocolMessageTypes.request_peers_introducer: RLSettings(100, 100),
            ProtocolMessageTypes.respond_peers_introducer: RLSettings(100, 1024 * 1024),
            ProtocolMessageTypes.farm_new_block: RLSettings(200, 200),
            ProtocolMessageTypes.request_plots: RLSettings(10, 10 * 1024 * 1024),
            ProtocolMessageTypes.respond_plots: RLSettings(10, 100 * 1024 * 1024),
            ProtocolMessageTypes.plot_sync_start: RLSettings(1000, 100 * 1024 * 1024),
            ProtocolMessageTypes.plot_sync_loaded: RLSettings(1000, 100 * 1024 * 1024),
            ProtocolMessageTypes.plot_sync_removed: RLSettings(1000, 100 * 1024 * 1024),
            ProtocolMessageTypes.plot_sync_invalid: RLSettings(1000, 100 * 1024 * 1024),
            ProtocolMessageTypes.plot_sync_keys_missing: RLSettings(1000, 100 * 1024 * 1024),
            ProtocolMessageTypes.plot_sync_duplicates: RLSettings(1000, 100 * 1024 * 1024),
            ProtocolMessageTypes.plot_sync_done: RLSettings(1000, 100 * 1024 * 1024),
            ProtocolMessageTypes.plot_sync_response: RLSettings(3000, 100 * 1024 * 1024),
            ProtocolMessageTypes.coin_state_update: RLSettings(1000, 100 * 1024 * 1024),
            ProtocolMessageTypes.register_interest_in_puzzle_hash: RLSettings(1000, 100 * 1024 * 1024),
            ProtocolMessageTypes.respond_to_ph_update: RLSettings(1000, 100 * 1024 * 1024),
            ProtocolMessageTypes.register_interest_in_coin: RLSettings(1000, 100 * 1024 * 1024),
            ProtocolMessageTypes.respond_to_coin_update: RLSettings(1000, 100 * 1024 * 1024),
            ProtocolMessageTypes.request_ses_hashes: RLSettings(2000, 1 * 1024 * 1024),
            ProtocolMessageTypes.respond_ses_hashes: RLSettings(2000, 1 * 1024 * 1024),
            ProtocolMessageTypes.request_children: RLSettings(2000, 1024 * 1024),
            ProtocolMessageTypes.respond_children: RLSettings(2000, 1 * 1024 * 1024),
        },
    },
    2: {
        "default_settings": RLSettings(100, 1024 * 1024, 100 * 1024 * 1024),
        "non_tx_freq": 1000,  # There is also a freq limit for many requests
        "non_tx_max_total_size": 100 * 1024 * 1024,  # There is also a size limit for many requests
        "rate_limits_tx": {
            ProtocolMessageTypes.request_block_header: RLSettings(500, 100),
            ProtocolMessageTypes.respond_block_header: RLSettings(500, 500 * 1024),
            ProtocolMessageTypes.reject_header_request: RLSettings(500, 100),
            ProtocolMessageTypes.request_removals: RLSettings(5000, 50 * 1024, 10 * 1024 * 1024),
            ProtocolMessageTypes.respond_removals: RLSettings(5000, 1024 * 1024, 10 * 1024 * 1024),
            ProtocolMessageTypes.reject_removals_request: RLSettings(500, 100),
            ProtocolMessageTypes.request_additions: RLSettings(50000, 100 * 1024 * 1024),
            ProtocolMessageTypes.respond_additions: RLSettings(50000, 100 * 1024 * 1024),
            ProtocolMessageTypes.reject_additions_request: RLSettings(500, 100),
            ProtocolMessageTypes.reject_header_blocks: RLSettings(1000, 100),
            ProtocolMessageTypes.respond_header_blocks: RLSettings(5000, 2 * 1024 * 1024),
            ProtocolMessageTypes.request_block_headers: RLSettings(5000, 100),
            ProtocolMessageTypes.reject_block_headers: RLSettings(1000, 100),
            ProtocolMessageTypes.respond_block_headers: RLSettings(5000, 2 * 1024 * 1024),
            ProtocolMessageTypes.request_ses_hashes: RLSettings(2000, 1 * 1024 * 1024),
            ProtocolMessageTypes.respond_ses_hashes: RLSettings(2000, 1 * 1024 * 1024),
            ProtocolMessageTypes.request_children: RLSettings(2000, 1024 * 1024),
            ProtocolMessageTypes.respond_children: RLSettings(2000, 1 * 1024 * 1024),
            ProtocolMessageTypes.request_puzzle_solution: RLSettings(5000, 100),
            ProtocolMessageTypes.respond_puzzle_solution: RLSettings(5000, 1024 * 1024),
            ProtocolMessageTypes.reject_puzzle_solution: RLSettings(5000, 100),
            ProtocolMessageTypes.none_response: RLSettings(500, 100),
            ProtocolMessageTypes.error: RLSettings(50000, 100),
        },
        "rate_limits_other": {  # These will have a lower cap since they don't scale with high TPS (NON_TX_FREQ)
            ProtocolMessageTypes.request_header_blocks: RLSettings(5000, 100),
        },
    },
}
