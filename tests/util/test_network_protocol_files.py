import logging
import os
import pytest
from tests.util.build_network_protocol_files import get_network_protocol_filename
from chia.protocols import (
    farmer_protocol,
    full_node_protocol,
    harvester_protocol,
    introducer_protocol,
    pool_protocol,
    timelord_protocol,
    wallet_protocol,
)
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

log = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop


def parse_blob(input_bytes):
    size_bytes = input_bytes[:4]
    input_bytes = input_bytes[4:]
    size = int.from_bytes(size_bytes, "big")
    message_bytes = input_bytes[:size]
    input_bytes = input_bytes[size:]
    return (message_bytes, input_bytes)


def parse_farmer_protocol(input_bytes):
    message_bytes, input_bytes = parse_blob(input_bytes)
    message = farmer_protocol.NewSignagePoint.from_bytes(message_bytes)
    assert message == new_signage_point
    assert message_bytes == bytes(new_signage_point)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = farmer_protocol.DeclareProofOfSpace.from_bytes(message_bytes)
    assert message == declare_proof_of_space
    assert message_bytes == bytes(declare_proof_of_space)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = farmer_protocol.RequestSignedValues.from_bytes(message_bytes)
    assert message == request_signed_values
    assert message_bytes == bytes(request_signed_values)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = farmer_protocol.FarmingInfo.from_bytes(message_bytes)
    assert message == farming_info
    assert message_bytes == bytes(farming_info)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = farmer_protocol.SignedValues.from_bytes(message_bytes)
    assert message == signed_values
    assert message_bytes == bytes(signed_values)

    return input_bytes


def parse_full_node_protocol(input_bytes):
    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.NewPeak.from_bytes(message_bytes)
    assert message == new_peak
    assert message_bytes == bytes(new_peak)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.NewTransaction.from_bytes(message_bytes)
    assert message == new_transaction
    assert message_bytes == bytes(new_transaction)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RequestTransaction.from_bytes(message_bytes)
    assert message == request_transaction
    assert message_bytes == bytes(request_transaction)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RespondTransaction.from_bytes(message_bytes)
    assert message == respond_transaction
    assert message_bytes == bytes(respond_transaction)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RequestProofOfWeight.from_bytes(message_bytes)
    assert message == request_proof_of_weight
    assert message_bytes == bytes(request_proof_of_weight)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RespondProofOfWeight.from_bytes(message_bytes)
    assert message == respond_proof_of_weight
    assert message_bytes == bytes(respond_proof_of_weight)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RequestBlock.from_bytes(message_bytes)
    assert message == request_block
    assert message_bytes == bytes(request_block)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RejectBlock.from_bytes(message_bytes)
    assert message == reject_block
    assert message_bytes == bytes(reject_block)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RequestBlocks.from_bytes(message_bytes)
    assert message == request_blocks
    assert message_bytes == bytes(request_blocks)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RespondBlocks.from_bytes(message_bytes)
    assert message == respond_blocks
    assert message_bytes == bytes(respond_blocks)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RejectBlocks.from_bytes(message_bytes)
    assert message == reject_blocks
    assert message_bytes == bytes(reject_blocks)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RespondBlock.from_bytes(message_bytes)
    assert message == respond_block
    assert message_bytes == bytes(respond_block)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.NewUnfinishedBlock.from_bytes(message_bytes)
    assert message == new_unfinished_block
    assert message_bytes == bytes(new_unfinished_block)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RequestUnfinishedBlock.from_bytes(message_bytes)
    assert message == request_unfinished_block
    assert message_bytes == bytes(request_unfinished_block)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RespondUnfinishedBlock.from_bytes(message_bytes)
    assert message == respond_unfinished_block
    assert message_bytes == bytes(respond_unfinished_block)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.NewSignagePointOrEndOfSubSlot.from_bytes(message_bytes)
    assert message == new_signage_point_or_end_of_subslot
    assert message_bytes == bytes(new_signage_point_or_end_of_subslot)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RequestSignagePointOrEndOfSubSlot.from_bytes(message_bytes)
    assert message == request_signage_point_or_end_of_subslot
    assert message_bytes == bytes(request_signage_point_or_end_of_subslot)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RespondSignagePoint.from_bytes(message_bytes)
    assert message == respond_signage_point
    assert message_bytes == bytes(respond_signage_point)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RespondEndOfSubSlot.from_bytes(message_bytes)
    assert message == respond_end_of_subslot
    assert message_bytes == bytes(respond_end_of_subslot)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RequestMempoolTransactions.from_bytes(message_bytes)
    assert message == request_mempool_transaction
    assert message_bytes == bytes(request_mempool_transaction)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.NewCompactVDF.from_bytes(message_bytes)
    assert message == new_compact_vdf
    assert message_bytes == bytes(new_compact_vdf)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RequestCompactVDF.from_bytes(message_bytes)
    assert message == request_compact_vdf
    assert message_bytes == bytes(request_compact_vdf)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RespondCompactVDF.from_bytes(message_bytes)
    assert message == respond_compact_vdf
    assert message_bytes == bytes(respond_compact_vdf)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RequestPeers.from_bytes(message_bytes)
    assert message == request_peers
    assert message_bytes == bytes(request_peers)

    message_bytes, input_bytes = parse_blob(input_bytes)
    message = full_node_protocol.RespondPeers.from_bytes(message_bytes)
    assert message == respond_peers
    assert message_bytes == bytes(respond_peers)    

    return input_bytes


class TestNetworkProtocolFiles:
    def test_network_protocol_files(self):
        filename = get_network_protocol_filename()
        assert os.path.exists(filename)
        with open(filename, "rb") as f:
            input_bytes = f.read()
        input_bytes = parse_farmer_protocol(input_bytes)
        input_bytes = parse_full_node_protocol(input_bytes)
        assert input_bytes == b""
