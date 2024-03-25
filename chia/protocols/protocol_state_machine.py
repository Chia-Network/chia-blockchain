from __future__ import annotations

from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.protocols.protocol_message_types import ProtocolMessageTypes as pmt

NO_REPLY_EXPECTED = [
    # full_node -> full_node messages
    pmt.new_peak,
    pmt.new_transaction,
    pmt.new_unfinished_block,
    pmt.new_unfinished_block2,
    pmt.new_signage_point_or_end_of_sub_slot,
    pmt.request_mempool_transactions,
    pmt.new_compact_vdf,
    pmt.coin_state_update,
]

"""
VALID_REPLY_MESSAGE_MAP:
key: sent message type.
value: valid reply message types, from the view of the requester.
A state machine can be built from this message map.
"""

VALID_REPLY_MESSAGE_MAP = {
    # messages for all services
    # pmt.handshake is handled in WSChiaConnection.perform_handshake
    # full_node -> full_node protocol messages
    pmt.request_transaction: [pmt.respond_transaction],
    pmt.request_proof_of_weight: [pmt.respond_proof_of_weight],
    pmt.request_block: [pmt.respond_block, pmt.reject_block],
    pmt.request_blocks: [pmt.respond_blocks, pmt.reject_blocks],
    pmt.request_unfinished_block: [pmt.respond_unfinished_block],
    pmt.request_unfinished_block2: [pmt.respond_unfinished_block],
    pmt.request_block_header: [pmt.respond_block_header, pmt.reject_header_request],
    pmt.request_removals: [pmt.respond_removals, pmt.reject_removals_request],
    pmt.request_additions: [pmt.respond_additions, pmt.reject_additions_request],
    pmt.request_signage_point_or_end_of_sub_slot: [pmt.respond_signage_point, pmt.respond_end_of_sub_slot],
    pmt.request_compact_vdf: [pmt.respond_compact_vdf],
    pmt.request_peers: [pmt.respond_peers],
    pmt.request_header_blocks: [pmt.respond_header_blocks, pmt.reject_header_blocks, pmt.reject_block_headers],
    pmt.register_interest_in_puzzle_hash: [pmt.respond_to_ph_update],
    pmt.register_interest_in_coin: [pmt.respond_to_coin_update],
    pmt.request_children: [pmt.respond_children],
    pmt.request_ses_hashes: [pmt.respond_ses_hashes],
    pmt.request_block_headers: [pmt.respond_block_headers, pmt.reject_block_headers, pmt.reject_header_blocks],
    pmt.request_peers_introducer: [pmt.respond_peers_introducer],
    pmt.request_puzzle_solution: [pmt.respond_puzzle_solution, pmt.reject_puzzle_solution],
    pmt.send_transaction: [pmt.transaction_ack],
}


def static_check_sent_message_response() -> None:
    """Check that allowed message data structures VALID_REPLY_MESSAGE_MAP and NO_REPLY_EXPECTED are consistent."""
    # Reply and non-reply sets should not overlap: This check should be static
    overlap = set(NO_REPLY_EXPECTED).intersection(set(VALID_REPLY_MESSAGE_MAP.keys()))
    if len(overlap) != 0:
        raise AssertionError(f"Overlapping NO_REPLY_EXPECTED and VALID_REPLY_MESSAGE_MAP values: {overlap}")


def message_requires_reply(sent: ProtocolMessageTypes) -> bool:
    """Return True if message has an entry in the full node P2P message map"""
    # If we knew the peer NodeType is FULL_NODE, we could also check `sent not in NO_REPLY_EXPECTED`
    return sent in VALID_REPLY_MESSAGE_MAP


def message_response_ok(sent: ProtocolMessageTypes, received: ProtocolMessageTypes) -> bool:
    """
    Check to see that peers respect protocol message types in reply.
    Call with received == None to indicate that we do not expect a specific reply message type.
    """
    # Errors below are runtime protocol message mismatches from peers
    if sent in VALID_REPLY_MESSAGE_MAP:
        return received in VALID_REPLY_MESSAGE_MAP[sent]

    return True


# Run `static_check_sent_message_response` to check this static invariant at import time
static_check_sent_message_response()
