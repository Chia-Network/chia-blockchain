# All of these rate limits scale with the number of transactions so the aggregate amounts are higher
import dataclasses
from typing import Optional

from chia.protocols.protocol_message_types import ProtocolMessageTypes


@dataclasses.dataclass(frozen=True)
class RLSettings:
    frequency: int
    max_size: int
    max_total_size: Optional[int] = None


DEFAULT_SETTINGS = RLSettings(100, 1024 * 1024, 100 * 1024 * 1024)

# All non-transaction apis also have an aggregate limit
NON_TX_FREQ = 1000
NON_TX_MAX_TOTAL_SIZE = 100 * 1024 * 1024

rate_limits = {
    1: {
        "rate_limits_tx": {
            ProtocolMessageTypes.new_transaction: RLSettings(5000, 100, 5000 * 100),
            ProtocolMessageTypes.request_transaction: RLSettings(5000, 100, 5000 * 100),
            ProtocolMessageTypes.respond_transaction: RLSettings(
                5000, 1 * 1024 * 1024, 20 * 1024 * 1024
            ),  # TODO: check this
            ProtocolMessageTypes.send_transaction: RLSettings(5000, 1024 * 1024),
            ProtocolMessageTypes.transaction_ack: RLSettings(5000, 2048),
            ProtocolMessageTypes.request_block_header: RLSettings(500, 100),
            ProtocolMessageTypes.respond_block_header: RLSettings(500, 500 * 1024),
            ProtocolMessageTypes.reject_header_request: RLSettings(500, 100),
            ProtocolMessageTypes.request_removals: RLSettings(5000, 50 * 1024, 10 * 1024 * 1024),
            ProtocolMessageTypes.respond_removals: RLSettings(5000, 1024 * 1024, 10 * 1024 * 1024),
            ProtocolMessageTypes.reject_removals_request: RLSettings(500, 100),
            ProtocolMessageTypes.request_additions: RLSettings(50000, 100 * 1024 * 1024),
            ProtocolMessageTypes.respond_additions: RLSettings(50000, 100 * 1024 * 1024),
            ProtocolMessageTypes.reject_additions_request: RLSettings(500, 100),
            ProtocolMessageTypes.request_header_blocks: RLSettings(5000, 100),
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
        },
        "other": {  # These will have a lower cap since they don't scale with high TPS (NON_TX_FREQ)
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
            ProtocolMessageTypes.new_peak_wallet: RLSettings(200, 300),
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
        },
    }
}
