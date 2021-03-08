import logging
import time
from enum import Enum

from src.protocols.protocol_message_types import ProtocolMessageTypes
from collections import Counter

from src.server.outbound_message import Message

log = logging.getLogger(__name__)


DEFAULT_PER_MINUTE_FREQ_LIMIT = 100
DEFAULT_MAX_SIZE = 1 * 1024 * 1024
DEFAULT_PER_MINUTE_SIZE_LIMIT = 10 * 1024 * 1024  # in bytes

# The three values in the tuple correspond to the three limits above
# The third is optional

rate_limits_tx = {
    ProtocolMessageTypes.new_transaction: (5000, 100, 5000 * 100),
    ProtocolMessageTypes.request_transaction: (5000, 100, 5000 * 100),
    ProtocolMessageTypes.respond_transaction: (5000, 1 * 1024 * 1024, 20 * 1024 * 1024),  # TODO: check this
    ProtocolMessageTypes.send_transaction: (5000, 1024 * 1024),
}

rate_limits_other = {
    ProtocolMessageTypes.handshake: (5, 10 * 1024, 5 * 10 * 1024),
    ProtocolMessageTypes.handshake_ack: (5, 1024),
    ProtocolMessageTypes.harvester_handshake: (5, 1024 * 1024),
    ProtocolMessageTypes.new_signage_point_harvester: (100, 1024),
    ProtocolMessageTypes.new_proof_of_space: (100, 2048),
    ProtocolMessageTypes.request_signatures: (100, 2048),
    ProtocolMessageTypes.respond_signatures: (100, 2048),
    ProtocolMessageTypes.new_signage_point: (200, 2048),
    ProtocolMessageTypes.declare_proof_of_space: (100, 10 * 1024),
    ProtocolMessageTypes.request_signed_values: (100, 512),
    ProtocolMessageTypes.farming_info: (100, 1024),
    ProtocolMessageTypes.signed_values: (100, 1024),
    ProtocolMessageTypes.new_peak_timelord: (100, 20 * 1024),
    ProtocolMessageTypes.new_unfinished_block_timelord: (100, 10 * 1024),
    ProtocolMessageTypes.new_infusion_point_vdf: (100, 100 * 1024),
    ProtocolMessageTypes.new_end_of_sub_slot_vdf: (100, 100 * 1024),
    ProtocolMessageTypes.new_peak: (100, 512),
    ProtocolMessageTypes.request_proof_of_weight: (5, 100),
    ProtocolMessageTypes.respond_proof_of_weight: (5, 100 * 1024 * 1024),
    ProtocolMessageTypes.request_block: (200, 100),
    ProtocolMessageTypes.reject_block: (200, 100),
    ProtocolMessageTypes.request_blocks: (100, 100),
    ProtocolMessageTypes.respond_blocks: (100, 50 * 1024 * 1024, 5 * 50 * 1024 * 1024),
    ProtocolMessageTypes.reject_blocks: (100, 100),
    ProtocolMessageTypes.respond_block: (200, 2 * 1024 * 1024, 10 * 2 * 1024 * 1024),
    ProtocolMessageTypes.new_unfinished_block: (200, 100),
    ProtocolMessageTypes.request_unfinished_block: (200, 100),
    ProtocolMessageTypes.respond_unfinished_block: (200, 2 * 1024 * 1024, 10 * 2 * 1024 * 1024),
    ProtocolMessageTypes.new_signage_point_or_end_of_sub_slot: (200, 200),
    ProtocolMessageTypes.request_signage_point_or_end_of_sub_slot: (200, 200),
    ProtocolMessageTypes.respond_signage_point: (200, 50 * 1024),
    ProtocolMessageTypes.respond_end_of_sub_slot: (100, 50 * 1024),
    ProtocolMessageTypes.request_mempool_transactions: (5, 1024 * 1024),
    ProtocolMessageTypes.request_compact_vdf: (100, 1024),
    ProtocolMessageTypes.respond_compact_vdf: (100, 100 * 1024),
    ProtocolMessageTypes.new_compact_vdf: (100, 1024),
    ProtocolMessageTypes.request_peers: (10, 100),
    ProtocolMessageTypes.respond_peers: (10, 10 * 1024 * 1024),
    ProtocolMessageTypes.request_puzzle_solution: (100, 100),
    ProtocolMessageTypes.respond_puzzle_solution: (100, 1024 * 1024),
    ProtocolMessageTypes.reject_puzzle_solution: (100, 100),
    ProtocolMessageTypes.transaction_ack: (5000, 2048),
    ProtocolMessageTypes.new_peak_wallet: (200, 300),
    ProtocolMessageTypes.request_block_header: (500, 100),
    ProtocolMessageTypes.reject_header_request: (500, 100),
    ProtocolMessageTypes.request_removals: (500, 50 * 1024, 50 * 50 * 1024),
    ProtocolMessageTypes.respond_removals: (500, 1024 * 1024, 50 * 1024 * 1024),
    ProtocolMessageTypes.reject_removals_request: (500, 100),
    ProtocolMessageTypes.request_additions: (500, 1024 * 1024, 50 * 1024 * 1024),
    ProtocolMessageTypes.respond_additions: (500, 1024 * 1024, 50 * 1024 * 1024),
    ProtocolMessageTypes.reject_additions_request: (500, 100),
    ProtocolMessageTypes.request_header_blocks: (100, 100),
    ProtocolMessageTypes.reject_header_blocks: (100, 100),
    ProtocolMessageTypes.respond_header_blocks: (100, 100 * 1024),
    ProtocolMessageTypes.request_peers_introducer: (100, 100),
    ProtocolMessageTypes.respond_peers_introducer: (100, 1024 * 1024),
    ProtocolMessageTypes.farm_new_block: (200, 200),
}


# TODO: only full node disconnects based on rate limits


class RateLimitResponse(Enum):
    SUCCESS = 0
    DISCONNECT = 1
    IGNORE = 2


class RateLimiter:
    def __init__(self):
        self.current_minute = time.time() // 60
        self.message_counts = Counter()

    def message_received(self, message: Message) -> RateLimitResponse:
        current_minute = time.time() // 60
        if current_minute != self.current_minute:
            self.current_minute = current_minute
            self.message_counts = Counter()
        try:
            message_type = ProtocolMessageTypes(message.type)
        except Exception as e:
            # TODO: check whether to dc here, or somewhere else
            log.error(f"Invalid message: {message.type}, {e}")
            return RateLimitResponse.DISCONNECT

        self.message_counts[message_type] += 1

        if message_type in rate_limits_tx:
            per_min_freq_limit, max_size, per_min_max_size = rate_limits_tx[message_type]
        elif message_type in rate_limits_other:
            per_min_freq_limit, max_size, per_min_max_size = rate_limits_other[message_type]
        else:
            log.warning(f"Message type {message_type} not found in rate limits")
            per_min_freq_limit, max_size, per_min_max_size = (
                DEFAULT_PER_MINUTE_SIZE_LIMIT,
                DEFAULT_MAX_SIZE,
                DEFAULT_PER_MINUTE_SIZE_LIMIT,
            )

        if self.message_counts[message_type] > per_min_freq_limit:
            if message_type == ProtocolMessageTypes.respond_peers:
                # Attackers can convince other peers to send this message, so we can't disconnect peers from it
                return RateLimitResponse.IGNORE
            return RateLimitResponse.DISCONNECT

        #     if self.message_counts[message_type] > rate_limits_tx[message_type][0]:
        #         return RateLimitResponse.DISCONNECT
        #     if len(message.data) > rate_limits_tx[message_type]
        # elif message_type in rate_limits_other:
        #     if self.message_counts[message_type] > rate_limits_other[message_type][0]:
        #         if message_type == ProtocolMessageTypes.respond_peers:
        #             # Attackers can convince other peers to send this message, so we can't disconnect peers from it
        #             return RateLimitResponse.IGNORE
        #         else:
        #             return RateLimitResponse.DISCONNECT
        # else:
        #     log.warning(f"Message type {message_type} not found in rate limits")
        #     if self.message_counts[message_type] > DEFAULT_PER_MINUTE_FREQ_LIMIT:
        #         return RateLimitResponse.DISCONNECT
