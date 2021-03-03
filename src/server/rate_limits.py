from src.protocols.protocol_message_types import ProtocolMessageTypes

# from src.server.outbound_message import Message

DEFAULT_PER_MINUTE_FREQ_LIMIT = 100
DEFAULT_PER_MINUTE_SIZE_LIMIT = 10 * 1024 * 1024  # in bytes
DEFAULT_MAX_SIZE = 1 * 1024 * 1024

override_limits = {
    ProtocolMessageTypes.handshake: (5, 1024),
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
    ProtocolMessageTypes.new_transaction: (5000, 100),
    ProtocolMessageTypes.request_transaction: (5000, 100),
    ProtocolMessageTypes.respond_transaction: (5000, 1 * 1024 * 1024),  # TODO: check this
    ProtocolMessageTypes.request_proof_of_weight: (5, 100),
    ProtocolMessageTypes.respond_proof_of_weight: (5, 100 * 1024 * 1024),
    ProtocolMessageTypes.request_block: (200, 100),
    ProtocolMessageTypes.reject_block: (200, 100),
    ProtocolMessageTypes.request_blocks: (100, 100),
    ProtocolMessageTypes.respond_blocks: (100, 50 * 1024 * 1024),
    ProtocolMessageTypes.reject_blocks: (100, 100),
    ProtocolMessageTypes.respond_block: (200, 2 * 1024 * 1024),
    ProtocolMessageTypes.new_unfinished_block: (200, 100),
    ProtocolMessageTypes.request_unfinished_block: (200, 100),
    ProtocolMessageTypes.respond_unfinished_block: (200, 2 * 1024 * 1024),
    ProtocolMessageTypes.new_signage_point_or_end_of_sub_slot: (200, 200),
    ProtocolMessageTypes.request_signage_point_or_end_of_sub_slot: (200, 200),
    ProtocolMessageTypes.respond_signage_point: (200, 50 * 1024),
    ProtocolMessageTypes.respond_end_of_sub_slot: (100, 50 * 1024),
    ProtocolMessageTypes.request_mempool_transactions: (5, 1024 * 1024),
    ProtocolMessageTypes.request_peers: (10, 100),
    ProtocolMessageTypes.respond_peers: (5, 1024 * 1024),
    ProtocolMessageTypes.request_puzzle_solution: (100, 100),
    ProtocolMessageTypes.respond_puzzle_solution: (100, 1024 * 1024),
    ProtocolMessageTypes.reject_puzzle_solution: (100, 100),
    ProtocolMessageTypes.send_transaction: (5000, 1024 * 1024),
    ProtocolMessageTypes.transaction_ack: (5000, 2048),
    ProtocolMessageTypes.new_peak_wallet: (200, 300),
    ProtocolMessageTypes.request_block_header: (500, 100),
    ProtocolMessageTypes.reject_header_request: (500, 100),
    ProtocolMessageTypes.request_removals: (500, 50 * 1024),
    ProtocolMessageTypes.respond_removals: (500, 1024 * 1024),
    ProtocolMessageTypes.reject_removals_request: (500, 100),
    ProtocolMessageTypes.request_additions: (500, 1024 * 1024),
    ProtocolMessageTypes.respond_additions: (500, 1024 * 1024),
    ProtocolMessageTypes.reject_additions_request: (500, 100),
    ProtocolMessageTypes.request_header_blocks: (100, 100),
    ProtocolMessageTypes.reject_header_blocks: (100, 100),
    ProtocolMessageTypes.respond_header_blocks: (100, 100 * 1024),
    ProtocolMessageTypes.request_peers_introducer: (100, 100),
    ProtocolMessageTypes.respond_peers_introducer: (100, 1024 * 1024),
    ProtocolMessageTypes.farm_new_block: (200, 200),
}

#
# class RateLimiter:
#     def __init__(self):
#         pass
#
#     def message_received(self, message: Message):
#         try:
#             message_type: ProtocolMessageTypes = ProtocolMessageTypes(message.type)
#         except Exception:
#             return
