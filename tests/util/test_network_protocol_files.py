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


class TestNetworkProtocolFiles:
    def test_network_protocol_files(self):
        filename = get_network_protocol_filename()
        assert os.path.exists(filename)
        with open(filename, "rb") as f:
            input_bytes = f.read()
        input_bytes = parse_farmer_protocol(input_bytes)
        assert input_bytes == b""
