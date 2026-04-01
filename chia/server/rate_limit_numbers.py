# All of these rate limits scale with the number of transactions so the aggregate amounts are higher
from __future__ import annotations

import dataclasses

from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.shared_protocol import Capability

compose_rate_limits_cache: dict[int, dict[ProtocolMessageTypes, RLSettings | Unlimited]] = {}


# this class is used to configure the *rate* limit for a message type. The
# limits are counts and size per 60 seconds.
@dataclasses.dataclass(frozen=True)
class RLSettings:
    # if true, messages affect and are limited by the per connection aggregate limiter,
    # which affects messages across message types
    aggregate_limit: bool
    frequency: int  # Max request per time period (ie 1 min)
    max_size: int  # Max size of each request
    max_total_size: int | None = None  # Max cumulative size of all requests in that period


# this class is used to indicate that a message type is not subject to a rate
# limit, but just a per-message size limit. This may be appropriate for response
# messages that are implicitly limited by their corresponding request message
# Unlimited message types are also not subject to the overall limit across all
# messages (just like messages in the "tx" category)
@dataclasses.dataclass(frozen=True)
class Unlimited:
    max_size: int  # Max size of each request


# for the aggregate limit, not all fields of RLSettings are used. Only "frequency" and "max_total_size"
aggregate_limit = RLSettings(
    aggregate_limit=False,
    frequency=1000,
    max_size=0,
    max_total_size=100 * 1024 * 1024,
)


def get_rate_limits_to_use(
    our_capabilities: list[Capability], peer_capabilities: list[Capability]
) -> tuple[dict[ProtocolMessageTypes, RLSettings | Unlimited], RLSettings]:
    # This will use the newest possible rate limits that both peers support. At this time there are only two
    # options, v1 and v2.

    if Capability.RATE_LIMITS_V2 in our_capabilities and Capability.RATE_LIMITS_V2 in peer_capabilities:
        # Use V2 rate limits
        if 2 in compose_rate_limits_cache:
            return compose_rate_limits_cache[2], aggregate_limit
        composed = {
            **rate_limits[1],
            **rate_limits[2],
        }
        compose_rate_limits_cache[2] = composed
        return composed, aggregate_limit
    else:
        # Use V1 rate limits
        return rate_limits[1], aggregate_limit


# Each number in this dict corresponds to a specific version of rate limits (1, 2,  etc).
# Version 1 includes the original limits for chia software from versions 1.0 to 1.4.
rate_limits: dict[int, dict[ProtocolMessageTypes, RLSettings | Unlimited]] = {
    1: {
        ProtocolMessageTypes.new_transaction: RLSettings(False, 5000, 100, 5000 * 100),
        ProtocolMessageTypes.request_transaction: RLSettings(False, 5000, 100, 5000 * 100),
        # TODO: check this
        ProtocolMessageTypes.respond_transaction: RLSettings(False, 5000, 1 * 1024 * 1024, 20 * 1024 * 1024),
        ProtocolMessageTypes.send_transaction: RLSettings(False, 5000, 1024 * 1024),
        ProtocolMessageTypes.transaction_ack: RLSettings(False, 5000, 2048),
        # All non-transaction apis also have an aggregate limit
        ProtocolMessageTypes.handshake: RLSettings(True, 5, 10 * 1024, 5 * 10 * 1024),
        ProtocolMessageTypes.harvester_handshake: RLSettings(True, 5, 1024 * 1024),
        ProtocolMessageTypes.new_signage_point_harvester: RLSettings(True, 100, 4886),  # Size with 100 pool list
        ProtocolMessageTypes.new_proof_of_space: RLSettings(True, 100, 2048),
        ProtocolMessageTypes.request_signatures: RLSettings(True, 100, 2048),
        ProtocolMessageTypes.respond_signatures: RLSettings(True, 100, 2048),
        ProtocolMessageTypes.new_signage_point: RLSettings(True, 200, 2048),
        ProtocolMessageTypes.declare_proof_of_space: RLSettings(True, 100, 10 * 1024),
        ProtocolMessageTypes.request_signed_values: RLSettings(True, 100, 10 * 1024),
        ProtocolMessageTypes.farming_info: RLSettings(True, 100, 1024),
        ProtocolMessageTypes.signed_values: RLSettings(True, 100, 1024),
        ProtocolMessageTypes.new_peak_timelord: RLSettings(True, 100, 20 * 1024),
        ProtocolMessageTypes.new_unfinished_block_timelord: RLSettings(True, 100, 10 * 1024),
        ProtocolMessageTypes.new_signage_point_vdf: RLSettings(True, 100, 100 * 1024),
        ProtocolMessageTypes.new_infusion_point_vdf: RLSettings(True, 100, 100 * 1024),
        ProtocolMessageTypes.new_end_of_sub_slot_vdf: RLSettings(True, 100, 100 * 1024),
        ProtocolMessageTypes.request_compact_proof_of_time: RLSettings(True, 100, 10 * 1024),
        ProtocolMessageTypes.respond_compact_proof_of_time: RLSettings(True, 100, 100 * 1024),
        ProtocolMessageTypes.new_peak: RLSettings(True, 200, 512),
        ProtocolMessageTypes.request_proof_of_weight: RLSettings(True, 5, 100),
        ProtocolMessageTypes.respond_proof_of_weight: RLSettings(True, 5, 50 * 1024 * 1024, 100 * 1024 * 1024),
        ProtocolMessageTypes.request_block: RLSettings(True, 200, 100),
        ProtocolMessageTypes.reject_block: Unlimited(100),
        ProtocolMessageTypes.request_blocks: RLSettings(True, 500, 100),
        ProtocolMessageTypes.respond_blocks: Unlimited(50 * 1024 * 1024),
        ProtocolMessageTypes.reject_blocks: Unlimited(100),
        ProtocolMessageTypes.respond_block: Unlimited(2 * 1024 * 1024),
        ProtocolMessageTypes.new_unfinished_block: RLSettings(True, 200, 100),
        ProtocolMessageTypes.request_unfinished_block: RLSettings(True, 200, 100),
        ProtocolMessageTypes.new_unfinished_block2: RLSettings(True, 200, 100),
        ProtocolMessageTypes.request_unfinished_block2: RLSettings(True, 200, 100),
        ProtocolMessageTypes.respond_unfinished_block: RLSettings(True, 200, 2 * 1024 * 1024, 10 * 2 * 1024 * 1024),
        ProtocolMessageTypes.new_signage_point_or_end_of_sub_slot: RLSettings(True, 200, 200),
        ProtocolMessageTypes.request_signage_point_or_end_of_sub_slot: RLSettings(True, 200, 200),
        ProtocolMessageTypes.respond_signage_point: RLSettings(True, 200, 50 * 1024),
        ProtocolMessageTypes.respond_end_of_sub_slot: RLSettings(True, 100, 50 * 1024),
        ProtocolMessageTypes.request_mempool_transactions: RLSettings(True, 5, 1024 * 1024),
        ProtocolMessageTypes.request_compact_vdf: RLSettings(True, 200, 1024),
        ProtocolMessageTypes.respond_compact_vdf: RLSettings(True, 200, 100 * 1024),
        ProtocolMessageTypes.new_compact_vdf: RLSettings(True, 100, 1024),
        ProtocolMessageTypes.request_peers: RLSettings(True, 10, 100),
        ProtocolMessageTypes.respond_peers: RLSettings(True, 10, 1 * 1024 * 1024),
        ProtocolMessageTypes.request_puzzle_solution: RLSettings(True, 1000, 100),
        ProtocolMessageTypes.respond_puzzle_solution: RLSettings(True, 1000, 1024 * 1024),
        ProtocolMessageTypes.reject_puzzle_solution: RLSettings(True, 1000, 100),
        ProtocolMessageTypes.none_response: RLSettings(False, 500, 100),
        ProtocolMessageTypes.new_peak_wallet: RLSettings(True, 200, 300),
        ProtocolMessageTypes.request_block_header: RLSettings(True, 500, 100),
        ProtocolMessageTypes.respond_block_header: RLSettings(True, 500, 500 * 1024),
        ProtocolMessageTypes.reject_header_request: RLSettings(True, 500, 100),
        ProtocolMessageTypes.request_block_headers: RLSettings(False, 5000, 100),
        ProtocolMessageTypes.reject_block_headers: RLSettings(False, 1000, 100),
        ProtocolMessageTypes.respond_block_headers: RLSettings(False, 5000, 2 * 1024 * 1024),
        ProtocolMessageTypes.request_removals: RLSettings(True, 500, 50 * 1024, 10 * 1024 * 1024),
        ProtocolMessageTypes.respond_removals: RLSettings(True, 500, 1024 * 1024, 10 * 1024 * 1024),
        ProtocolMessageTypes.reject_removals_request: RLSettings(True, 500, 100),
        ProtocolMessageTypes.request_additions: RLSettings(True, 500, 1024 * 1024, 10 * 1024 * 1024),
        ProtocolMessageTypes.respond_additions: RLSettings(True, 500, 1024 * 1024, 10 * 1024 * 1024),
        ProtocolMessageTypes.reject_additions_request: RLSettings(True, 500, 100),
        ProtocolMessageTypes.request_header_blocks: RLSettings(True, 500, 100),
        ProtocolMessageTypes.reject_header_blocks: RLSettings(True, 100, 100),
        ProtocolMessageTypes.respond_header_blocks: RLSettings(True, 500, 2 * 1024 * 1024, 100 * 1024 * 1024),
        ProtocolMessageTypes.request_peers_introducer: RLSettings(True, 100, 100),
        ProtocolMessageTypes.respond_peers_introducer: RLSettings(True, 100, 1024 * 1024),
        ProtocolMessageTypes.farm_new_block: RLSettings(True, 200, 200),
        ProtocolMessageTypes.request_plots: RLSettings(True, 10, 10 * 1024 * 1024),
        ProtocolMessageTypes.respond_plots: RLSettings(True, 10, 100 * 1024 * 1024),
        ProtocolMessageTypes.plot_sync_start: RLSettings(True, 1000, 100 * 1024 * 1024),
        ProtocolMessageTypes.plot_sync_loaded: RLSettings(True, 1000, 100 * 1024 * 1024),
        ProtocolMessageTypes.plot_sync_removed: RLSettings(True, 1000, 100 * 1024 * 1024),
        ProtocolMessageTypes.plot_sync_invalid: RLSettings(True, 1000, 100 * 1024 * 1024),
        ProtocolMessageTypes.plot_sync_keys_missing: RLSettings(True, 1000, 100 * 1024 * 1024),
        ProtocolMessageTypes.plot_sync_duplicates: RLSettings(True, 1000, 100 * 1024 * 1024),
        ProtocolMessageTypes.plot_sync_done: RLSettings(True, 1000, 100 * 1024 * 1024),
        ProtocolMessageTypes.plot_sync_response: RLSettings(True, 3000, 100 * 1024 * 1024),
        ProtocolMessageTypes.coin_state_update: RLSettings(True, 1000, 100 * 1024 * 1024),
        ProtocolMessageTypes.register_for_ph_updates: RLSettings(True, 1000, 100 * 1024 * 1024),
        ProtocolMessageTypes.respond_to_ph_updates: RLSettings(True, 1000, 100 * 1024 * 1024),
        ProtocolMessageTypes.register_for_coin_updates: RLSettings(True, 1000, 100 * 1024 * 1024),
        ProtocolMessageTypes.respond_to_coin_updates: RLSettings(True, 1000, 100 * 1024 * 1024),
        ProtocolMessageTypes.request_remove_puzzle_subscriptions: RLSettings(True, 1000, 100 * 1024 * 1024),
        ProtocolMessageTypes.respond_remove_puzzle_subscriptions: RLSettings(True, 1000, 100 * 1024 * 1024),
        ProtocolMessageTypes.request_remove_coin_subscriptions: RLSettings(True, 1000, 100 * 1024 * 1024),
        ProtocolMessageTypes.respond_remove_coin_subscriptions: RLSettings(True, 1000, 100 * 1024 * 1024),
        ProtocolMessageTypes.request_puzzle_state: RLSettings(True, 1000, 100 * 1024 * 1024),
        ProtocolMessageTypes.respond_puzzle_state: RLSettings(True, 1000, 100 * 1024 * 1024),
        ProtocolMessageTypes.reject_puzzle_state: RLSettings(True, 200, 100),
        ProtocolMessageTypes.request_coin_state: RLSettings(True, 1000, 100 * 1024 * 1024),
        ProtocolMessageTypes.respond_coin_state: RLSettings(True, 1000, 100 * 1024 * 1024),
        ProtocolMessageTypes.reject_coin_state: RLSettings(True, 200, 100),
        ProtocolMessageTypes.mempool_items_added: RLSettings(True, 1000, 100 * 1024 * 1024),
        ProtocolMessageTypes.mempool_items_removed: RLSettings(True, 1000, 100 * 1024 * 1024),
        ProtocolMessageTypes.request_cost_info: RLSettings(True, 1000, 100),
        ProtocolMessageTypes.respond_cost_info: RLSettings(True, 1000, 1024),
        ProtocolMessageTypes.request_ses_hashes: RLSettings(True, 2000, 1 * 1024 * 1024),
        ProtocolMessageTypes.respond_ses_hashes: RLSettings(True, 2000, 1 * 1024 * 1024),
        ProtocolMessageTypes.request_children: RLSettings(True, 2000, 1024 * 1024),
        ProtocolMessageTypes.respond_children: RLSettings(True, 2000, 1 * 1024 * 1024),
        ProtocolMessageTypes.error: RLSettings(False, 50000, 100),
        ProtocolMessageTypes.request_fee_estimates: RLSettings(True, 10, 100),
        ProtocolMessageTypes.respond_fee_estimates: RLSettings(True, 10, 100),
        ProtocolMessageTypes.solve: RLSettings(False, 120, 1024),
        ProtocolMessageTypes.solution_response: RLSettings(False, 120, 1024),
        ProtocolMessageTypes.partial_proofs: RLSettings(False, 120, 3 * 1024),
    },
    2: {
        ProtocolMessageTypes.request_block_header: RLSettings(False, 500, 100),
        ProtocolMessageTypes.respond_block_header: RLSettings(False, 500, 500 * 1024),
        ProtocolMessageTypes.reject_header_request: RLSettings(False, 500, 100),
        ProtocolMessageTypes.request_removals: RLSettings(False, 5000, 50 * 1024, 10 * 1024 * 1024),
        ProtocolMessageTypes.respond_removals: RLSettings(False, 5000, 1024 * 1024, 10 * 1024 * 1024),
        ProtocolMessageTypes.reject_removals_request: RLSettings(False, 500, 100),
        ProtocolMessageTypes.request_additions: RLSettings(False, 50000, 100 * 1024 * 1024),
        ProtocolMessageTypes.respond_additions: RLSettings(False, 50000, 100 * 1024 * 1024),
        ProtocolMessageTypes.reject_additions_request: RLSettings(False, 500, 100),
        ProtocolMessageTypes.reject_header_blocks: RLSettings(False, 1000, 100),
        ProtocolMessageTypes.respond_header_blocks: RLSettings(False, 5000, 2 * 1024 * 1024),
        ProtocolMessageTypes.request_ses_hashes: RLSettings(False, 2000, 1 * 1024 * 1024),
        ProtocolMessageTypes.respond_ses_hashes: RLSettings(False, 2000, 1 * 1024 * 1024),
        ProtocolMessageTypes.request_children: RLSettings(False, 2000, 1024 * 1024),
        ProtocolMessageTypes.respond_children: RLSettings(False, 2000, 1 * 1024 * 1024),
        ProtocolMessageTypes.request_puzzle_solution: RLSettings(False, 5000, 100),
        ProtocolMessageTypes.respond_puzzle_solution: RLSettings(False, 5000, 1024 * 1024),
        ProtocolMessageTypes.reject_puzzle_solution: RLSettings(False, 5000, 100),
        # These will have a lower cap since they don't scale with high TPS (NON_TX_FREQ)
        ProtocolMessageTypes.request_header_blocks: RLSettings(True, 5000, 100),
    },
}
