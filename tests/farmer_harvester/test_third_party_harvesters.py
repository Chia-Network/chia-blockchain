from __future__ import annotations

import asyncio
import base64
import dataclasses
from typing import Any, List, Optional, Tuple, Union, cast


import pytest
from pytest_mock import MockerFixture
from chia.consensus.blockchain import AddBlockResult
from chia.consensus.multiprocess_validation import PreValidationResult
from chia.consensus.vdf_info_computation import get_signage_point_vdf_info

from chia.farmer.farmer import Farmer, calculate_harvester_fee_quality
from chia.farmer.farmer_api import FarmerAPI
from chia.full_node.full_node import FullNode
from chia.full_node.full_node_api import FullNodeAPI
from chia.harvester.harvester import Harvester
from chia.harvester.harvester_api import HarvesterAPI
from chia.protocols import full_node_protocol, harvester_protocol, timelord_protocol
from chia.protocols import farmer_protocol
from chia.protocols.farmer_protocol import RequestSignedValues
from chia.protocols.harvester_protocol import ProofOfSpaceFeeInfo, RespondSignatures, SigningDataKind
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.outbound_message import Message, NodeType, make_msg
from chia.server.server import ChiaServer
from chia.server.start_service import Service
from chia.server.ws_connection import WSChiaConnection
from chia.simulator.block_tools import BlockTools, get_signage_point
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.timelord.timelord import Timelord
from chia.timelord.timelord_api import TimelordAPI
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.foliage import FoliageBlockData, FoliageTransactionBlock
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.slots import ChallengeChainSubSlot, RewardChainSubSlot
from chia.types.blockchain_format.vdf import validate_vdf
from chia.types.full_block import FullBlock
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.types.peer_info import UnresolvedPeerInfo
from chia.types.unfinished_block import UnfinishedBlock
from chia.util.bech32m import decode_puzzle_hash
from chia.util.ints import uint8, uint32
from chia.util.streamable import Streamable
import json
from tests.util.time_out_assert import time_out_assert


# Pre-generated test signage points encoded as base64.
# Each element contains either a NewSignagePointVDF or a NewEndOfSubSlotVDF.
# If the first element of the tuple is True, then it is as NewEndOfSubSlotVDF.
# A FullBlock is also included which is infused already in the chain so
# that the next NewEndOfSubSlotVDF is valid.
# This block has to be added to the test FullNode before injecting the signage points.
test_data = {
  "block": "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",
  "signage_points": [
    [False, "BOOwxEKY/BwUmvv0yJlvuSQnrkHkZJuTTKSVmRt4UrhVAAAAAAAIAAADAF9Pqr5864eW4tjbPbZmISJzli4r8elRcXNS4NKE7HsY9Fldr9t+3U4OKueyMbznynX1Ua/OpRsyZ5cTqgH69i83X4Ieg1wzPMLSpNjJ5e2q4XAt2C8fndY4QeVy31h9EQEAAgAAAX4DAIXnQ0/vPG4mP9tgWhSOSDCKf799bXJX1FBuxFL3M5g6b8TwkdwcV8wz3fmucNMr1oXnQe357uwZdMssA/Fl/hpbg9tsKUWU4AeL6fww5f8NJgxIyAYbm/9nyV9nWnsiLgEAAAAAAAABxxTvgblTRaKn7eRrc/nXRi3rsWXdZ5x3J3d1zNjv1QRtZX0CALaQBm6XXWjYlWslsE4G7b6x3b43uXOcoQP1u3zixxvfHUn6hR4X2tRX8qdwyx9YFJVyyNkjt1b0qKKMU8Wb3Chh6ov/RmE6SdcgY9YLb8exhBM69Npu2g1z9j/oCPYUMQEAAAAAAAAFVTy2Yks9w7adJGpHszOrhvfAvVs0iWoGIit6ilvXqgu/jZ0DAFTvXpvA2d71INC453oGN5dpX8xkMbgNI6spqZUPAB3woR6Gg4PCR7CX8RxR+WPrTKHOyDla1QJK4PYM1qfh3SHfl66GmccZYwwD3uRw8TgUZcxe+hud9OohZ5032VaXPgEAAOOwxEKY/BwUmvv0yJlvuSQnrkHkZJuTTKSVmRt4UrhVAAAAAAAIAAADAF9Pqr5864eW4tjbPbZmISJzli4r8elRcXNS4NKE7HsY9Fldr9t+3U4OKueyMbznynX1Ua/OpRsyZ5cTqgH69i83X4Ieg1wzPMLSpNjJ5e2q4XAt2C8fndY4QeVy31h9EQEAAgAAAX4DAIXnQ0/vPG4mP9tgWhSOSDCKf799bXJX1FBuxFL3M5g6b8TwkdwcV8wz3fmucNMr1oXnQe357uwZdMssA/Fl/hpbg9tsKUWU4AeL6fww5f8NJgxIyAYbm/9nyV9nWnsiLgEAAAAAAAABxxTvgblTRaKn7eRrc/nXRi3rsWXdZ5x3J3d1zNjv1QRtZX0CALaQBm6XXWjYlWslsE4G7b6x3b43uXOcoQP1u3zixxvfHUn6hR4X2tRX8qdwyx9YFJVyyNkjt1b0qKKMU8Wb3Chh6ov/RmE6SdcgY9YLb8exhBM69Npu2g1z9j/oCPYUMQEAAAAAAAAFVTy2Yks9w7adJGpHszOrhvfAvVs0iWoGIit6ilvXqgu/jZ0DAFTvXpvA2d71INC453oGN5dpX8xkMbgNI6spqZUPAB3woR6Gg4PCR7CX8RxR+WPrTKHOyDla1QJK4PYM1qfh3SHfl66GmccZYwwD3uRw8TgUZcxe+hud9OohZ5032VaXPgEAAA=="],
    [False, "BeOwxEKY/BwUmvv0yJlvuSQnrkHkZJuTTKSVmRt4UrhVAAAAAAAKAAAAABXjy8RsXbUvVrSzmVDG9YSk68uCAWJL1uoO3E2jgWzbCn8ggiPoxOm9XMw0ZSekpfzULKUqMxGCcl5SxKRLfl2/xNSI6S4gcGsNRKOEIk52cN2UMGi0SaZ2gowZZOj7JwEAAgAAAX4CAJWBp2UDnYvlQJzlzeP1OuLr4aYHmcD0XyuF0rCPA/laed3duSi2u/fGqJMQlmbcZZhRJhutABSDXgGNQjzR7wEFJgBAKxgKGSvdNyNc5eMhOEngmK9hUfMD/JQkhWMnBQYAAAAAAAACOMDtuyBUHMoe8UQql+cSPLeX+e2imJoduK2MMrZoPVsvMakDABri6L5LI+MHJ5w2RnokG61SWqxNuYXSWU2zbHb2oEXXcl1yU+Y+KZSckPywfQ4azFXb7UXWjy6k25pJdJ1F2w0/C879hlCjRKfUcdqhrHA7fn4larAy+ezGlDVYf7tLAwEAAAAAAAAGqqTB+JyozfECvPY9ZZJCiYWP7AkoBgvKLzt4xF2AeRHMEqEBAH4VLZ25E9yTjT8VWAg04TGrPLV/wWTkHA8hlHUkOLe9jGBwTnmz2RM0R8qzrC2EzHeon7+aXT5t/NQV8hbynSbbFUIMdyffE/LJG7jtZQVzjZtFdRCLpqopgQLlj69mKwIBAOOwxEKY/BwUmvv0yJlvuSQnrkHkZJuTTKSVmRt4UrhVAAAAAAAKAAAAABXjy8RsXbUvVrSzmVDG9YSk68uCAWJL1uoO3E2jgWzbCn8ggiPoxOm9XMw0ZSekpfzULKUqMxGCcl5SxKRLfl2/xNSI6S4gcGsNRKOEIk52cN2UMGi0SaZ2gowZZOj7JwEAAgAAAX4CAJWBp2UDnYvlQJzlzeP1OuLr4aYHmcD0XyuF0rCPA/laed3duSi2u/fGqJMQlmbcZZhRJhutABSDXgGNQjzR7wEFJgBAKxgKGSvdNyNc5eMhOEngmK9hUfMD/JQkhWMnBQYAAAAAAAACOMDtuyBUHMoe8UQql+cSPLeX+e2imJoduK2MMrZoPVsvMakDABri6L5LI+MHJ5w2RnokG61SWqxNuYXSWU2zbHb2oEXXcl1yU+Y+KZSckPywfQ4azFXb7UXWjy6k25pJdJ1F2w0/C879hlCjRKfUcdqhrHA7fn4larAy+ezGlDVYf7tLAwEAAAAAAAAGqqTB+JyozfECvPY9ZZJCiYWP7AkoBgvKLzt4xF2AeRHMEqEBAH4VLZ25E9yTjT8VWAg04TGrPLV/wWTkHA8hlHUkOLe9jGBwTnmz2RM0R8qzrC2EzHeon7+aXT5t/NQV8hbynSbbFUIMdyffE/LJG7jtZQVzjZtFdRCLpqopgQLlj69mKwIBAA=="],
    [False, "BuOwxEKY/BwUmvv0yJlvuSQnrkHkZJuTTKSVmRt4UrhVAAAAAAAMAAABAAfCTnH4z/tATKEUM3sLqYL8ZhDIZsTwzJJBuL3B1wPvTpsKXibzwp2L3QpjL8pace8XHnXKFQLM5qW1gHZnZ0mPZ2M5nZ3tbrFvwW6Ri0jigWLo5b0GRlcek5qsoAX2NAEAAgAAAX4CAAMIPyF8RLPT+pJysZsSQZ3umM3ngelBF+69CsEynDE0haMgM4i4RztuGonuO487Djp7Ux0Is8nYGNL4iq4yUS1YmjKAsyQDgJU+Lwf5ZNFI89/7/tYmuDNH1TM86ctkDwEAAAAAAAACqtDBTKdKMp9LUHyuLQypw/lw2e/5NcxpbGjnYJoSyWOwp38BALmXOMvsg2Y7AzY5A51xgpHFmEQXsdE4hUzulncl0JCKS/bzX+BypUff33szDSsYA+MQgYgqdIfqyXmaKW8Emw5YhE5TKLmrbrhDx8vzNJl8Ory9EBcGGpesM2SS6z+oAgYFAAAAAAAH/6idNPcaECeISGXZFdp99YZuSj/J9S2bAbOGuysDr4SU4V0BAOvQCHEbCAm0FeV5VkvvfGvFxAmdFTQrW2KUvJUpLWHO5OpNQuLbSuHr573B40IFXS7cRybMJLHRITUgQfv9gzNQUqZpKkW7BB0vGSxbBtFMfiMyCRK1gBPFI5/zWC8hOwEAAOOwxEKY/BwUmvv0yJlvuSQnrkHkZJuTTKSVmRt4UrhVAAAAAAAMAAABAAfCTnH4z/tATKEUM3sLqYL8ZhDIZsTwzJJBuL3B1wPvTpsKXibzwp2L3QpjL8pace8XHnXKFQLM5qW1gHZnZ0mPZ2M5nZ3tbrFvwW6Ri0jigWLo5b0GRlcek5qsoAX2NAEAAgAAAX4CAAMIPyF8RLPT+pJysZsSQZ3umM3ngelBF+69CsEynDE0haMgM4i4RztuGonuO487Djp7Ux0Is8nYGNL4iq4yUS1YmjKAsyQDgJU+Lwf5ZNFI89/7/tYmuDNH1TM86ctkDwEAAAAAAAACqtDBTKdKMp9LUHyuLQypw/lw2e/5NcxpbGjnYJoSyWOwp38BALmXOMvsg2Y7AzY5A51xgpHFmEQXsdE4hUzulncl0JCKS/bzX+BypUff33szDSsYA+MQgYgqdIfqyXmaKW8Emw5YhE5TKLmrbrhDx8vzNJl8Ory9EBcGGpesM2SS6z+oAgYFAAAAAAAH/6idNPcaECeISGXZFdp99YZuSj/J9S2bAbOGuysDr4SU4V0BAOvQCHEbCAm0FeV5VkvvfGvFxAmdFTQrW2KUvJUpLWHO5OpNQuLbSuHr573B40IFXS7cRybMJLHRITUgQfv9gzNQUqZpKkW7BB0vGSxbBtFMfiMyCRK1gBPFI5/zWC8hOwEAAA=="],
    [False, "B+OwxEKY/BwUmvv0yJlvuSQnrkHkZJuTTKSVmRt4UrhVAAAAAAAOAAADADve9/PwoEXv54o6mwTagkH4wvLHOtp1K8RWP43GdNyrXOUFRix8kqhVwdFUBnB7hB6MSxSYnWTGyMMoGjdjcy/vJ9IQFb9SaoRwVqMu+Le+6RbdErYOqQ7OEpD7VJdHDQIBAgAAAX4CAEey9G7F33NNDJUN80MgIe00mRZTYFAk3OYhXPCt+eOXgq166apGQAcgNFIVr2Nh8+BTxpxVjcJhAGc30o8+yAlj49pZKDQzQpIVnlC/I0pzcKK+9BvvSqo1ZzLw0sYVCgEAAAAAAAADHHy/reKO958YCcXvYDf4qpP4dqj/YNzYQVFo6SIoBf08sHEDADGNTq9S8OlxPUS6gV5GGThItn4ouJMWGFLmu+514+qMoszYkhZAaRmqDPhTYas8QbG1A8JO8bjkH/Hh8wvqWg7l/4QFYeRUktlsYFDReFhhRETliw42NXw3pNK/E178GQIBAAAAAAAJVRDOFOGylOWfk7clcgLbKw7OCXeR33Gz4CMcXkqKS1XZrEkDAKXBlcajDHPWVrmJeZLdFLZZ67ck6/v7nz4o5w4AIHFGUYmEifx89gAKNagsk4dmG7zMCvKiepV45haXB5MKABCrG1SaogF+t1vbO/181W8iI+SFLyV9W1exSYKdVRx6GAEAAOOwxEKY/BwUmvv0yJlvuSQnrkHkZJuTTKSVmRt4UrhVAAAAAAAOAAADADve9/PwoEXv54o6mwTagkH4wvLHOtp1K8RWP43GdNyrXOUFRix8kqhVwdFUBnB7hB6MSxSYnWTGyMMoGjdjcy/vJ9IQFb9SaoRwVqMu+Le+6RbdErYOqQ7OEpD7VJdHDQIBAgAAAX4CAEey9G7F33NNDJUN80MgIe00mRZTYFAk3OYhXPCt+eOXgq166apGQAcgNFIVr2Nh8+BTxpxVjcJhAGc30o8+yAlj49pZKDQzQpIVnlC/I0pzcKK+9BvvSqo1ZzLw0sYVCgEAAAAAAAADHHy/reKO958YCcXvYDf4qpP4dqj/YNzYQVFo6SIoBf08sHEDADGNTq9S8OlxPUS6gV5GGThItn4ouJMWGFLmu+514+qMoszYkhZAaRmqDPhTYas8QbG1A8JO8bjkH/Hh8wvqWg7l/4QFYeRUktlsYFDReFhhRETliw42NXw3pNK/E178GQIBAAAAAAAJVRDOFOGylOWfk7clcgLbKw7OCXeR33Gz4CMcXkqKS1XZrEkDAKXBlcajDHPWVrmJeZLdFLZZ67ck6/v7nz4o5w4AIHFGUYmEifx89gAKNagsk4dmG7zMCvKiepV45haXB5MKABCrG1SaogF+t1vbO/181W8iI+SFLyV9W1exSYKdVRx6GAEAAA=="],
    [False, "B+OwxEKY/BwUmvv0yJlvuSQnrkHkZJuTTKSVmRt4UrhVAAAAAAAOAAADADve9/PwoEXv54o6mwTagkH4wvLHOtp1K8RWP43GdNyrXOUFRix8kqhVwdFUBnB7hB6MSxSYnWTGyMMoGjdjcy/vJ9IQFb9SaoRwVqMu+Le+6RbdErYOqQ7OEpD7VJdHDQIBAgAAAX4AALKiYlqIVbCGJIG62TNvxZohoDWu4jjX6gnSr0g2XiC+tKsOqct5+uFU5u7wZpCiTEmwh9vWkAzTfaT8oojmXhiT+rHj6/HXgMWzMFJSfVegDytqGKk0dwgsEBgS/rdeAgEAAAAAAAAAcUiW24/5D+N9hl7EwkGsJQPqDjP1PggPknzW6gdQzON5XOMDAIfntgTuAecOYuCpjhT8J8q034eNdvyXxyU7BKV/f8rINhnfd+TmwOIs4hy1KUmaSJlNb14yWEwVTgC0TmSr5UPGE3PtfOpNBWJ18JqttDbtFOmIEnBa1JGBlcjYn1NPQwEAAAAAAAABVKD+rwh3VNv591aLstY+RWFC2Afof7oOpnBWgD5BLiv7prkDANNsqOaZJysO27Vkb0Gvqg3SAqSBpBuHACrqbdltvRzkschgkG72L2cJBdwYPzDAP+7wwQUi7WAD074JEM7gaQh5ZpRkr9o55hdytVYJllez/xQuuBsk/GpZc7pTWKPiHAIBAKp9N4Z1TvuirQv+Fatxz++ejWT9Er1aixkzXHaAE4j6AAAAAAAB/x0BANvkpbnjnFI4CtQ9rh6TDbpyT5mM9rN/LsZN9p0EAyFfXvUvfH8M4Nd2vGx5lpbYlwi9yMB7Ukd1GPTxRjI21husIYeNZPq6rwkU97qKZ1yjTk7S+nqhxP+Qc/LXIEIVDQEAAgAAAX4DAFHSrIIB4v/1YrMPNo1007HW0rhmz72JWgOdtXN+AvLFB9GaIk2c18URo6N4w2N9zMnddicEe9jLxGH0sP87SAzooZivp8fj2xZAd7oD+rPLfzc+C+qIFRAUMH0XMySICAIBAAAAAAAAcUjHHN/i/BrmF5iO3yN3G7JxUnonOynW4svL7PmUmmPZmlsDACqmxC2lb6NT+uIfF5GVDWWiiHD5cVRuKDZtxnG0ohuhAZpwJn0tgQVMb4KOyYYig01Tzq8uc+n0dQJaMwoZxWU/qt0TXGnZxdT57vqZ2uG3WtJqceFr4bAtbnOOIEQUfwEAAAAAAAABVKCLfkdNmP0DSAkT4DTFKWMvQHaKLacsYiwuvwBNk0INlIMCAHHHqeLZigtLhZ4eiW8iqIlLxD5MiZpTyEo4dR+pLpc/YZkEFvzooIh1Nwqq9NCLNhCtlpzIsXkcggBSai8lrApogRgRdCicLfREkK5shfjBoA+IKNux1EiB7fZnU8ahEwYAAA=="],
    [True, "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"],
  ]
}

SPType = Union[timelord_protocol.NewEndOfSubSlotVDF, timelord_protocol.NewSignagePointVDF]
SPList = List[SPType]

@pytest.mark.anyio
async def test_harvester_receive_source_signing_data(
    farmer_harvester_2_simulators_zero_bits_plot_filter:
    Tuple[
        Service[Farmer, FarmerAPI],
        Service[Harvester, HarvesterAPI],
        Union[Service[FullNode, FullNodeAPI], Service[FullNode, FullNodeSimulator]],
        Union[Service[FullNode, FullNodeAPI], Service[FullNode, FullNodeSimulator]],
        BlockTools,
    ],
    mocker: MockerFixture,
) -> None:
    """
    Tests that the source data for the signatures requests sent to the
    harvester are indeed available and also tests that overrides of
    the farmer reward address, as specified by the harvester, are respected.
    See: CHIP-22: https://github.com/Chia-Network/chips/pull/88
    """
    (
        farmer_service,
        harvester_service,
        full_node_service_1,
        full_node_service_2,
        _,
    ) = farmer_harvester_2_simulators_zero_bits_plot_filter

    farmer: Farmer = farmer_service._node
    harvester: Harvester = harvester_service._node
    full_node_1: FullNode = full_node_service_1._node
    full_node_2: FullNode = full_node_service_2._node

    # Connect peers to each other
    farmer_service.add_peer(
        UnresolvedPeerInfo(str(full_node_service_2.self_hostname), full_node_service_2._server.get_port())
    )
    full_node_service_2.add_peer(
        UnresolvedPeerInfo(str(full_node_service_1.self_hostname), full_node_service_1._server.get_port())
    )

    await wait_until_node_type_connected(farmer.server, NodeType.FULL_NODE)
    await wait_until_node_type_connected(farmer.server, NodeType.HARVESTER)         # Should already be connected
    await wait_until_node_type_connected(full_node_1.server, NodeType.FULL_NODE)


    # Prepare test data
    blocks: List[FullBlock]
    signage_points: SPList

    (blocks, signage_points) = load_test_data()
    assert len(blocks) == 1

    # Inject full node with a pre-existing block to skip initial genesis sub-slot
    # so that we have blocks generated that have our farmer reward address, instead
    # of the GENESIS_PRE_FARM_FARMER_PUZZLE_HASH.
    await add_test_blocks_into_full_node(blocks, full_node_2)


    validated_foliage_data = False
    validated_foliage_transaction = False
    validated_cc_vdf = False
    validated_rc_vdf = False
    validated_sub_slot_cc = False
    validated_sub_slot_rc = False
    # validated_partial = False     # Not covered currently. See comment in validate_harvester_request_signatures

    finished_validating_data = False
    farmer_reward_address = decode_puzzle_hash("txch1psqeaw0h244v5sy2r4se8pheyl62n8778zl6t5e7dep0xch9xfkqhx2mej")

    async def intercept_harvester_request_signatures(*args: Any) -> Message:
        request: harvester_protocol.RequestSignatures = harvester_protocol.RequestSignatures.from_bytes(args[0])
        nonlocal harvester
        nonlocal farmer_reward_address

        validate_harvester_request_signatures(request)
        result_msg: Optional[Message] = await HarvesterAPI.request_signatures(
            cast(HarvesterAPI, harvester.server.api), request
        )
        assert result_msg is not None

        # Inject overridden farmer reward address
        response: RespondSignatures = dataclasses.replace(
            RespondSignatures.from_bytes(result_msg.data), farmer_reward_address_override=farmer_reward_address
        )

        return make_msg(ProtocolMessageTypes.respond_signatures, response)

    def validate_harvester_request_signatures(request: harvester_protocol.RequestSignatures) -> None:
        nonlocal full_node_2
        nonlocal farmer_reward_address
        nonlocal validated_foliage_data
        nonlocal validated_foliage_transaction
        nonlocal validated_cc_vdf
        nonlocal validated_rc_vdf
        nonlocal validated_sub_slot_cc
        nonlocal validated_sub_slot_rc
        nonlocal finished_validating_data

        assert request.message_data is not None
        assert len(request.messages) > 0
        assert len(request.messages) == len(request.message_data)

        for hash, src in zip(request.messages, request.message_data):
            assert hash
            assert src

            data: Optional[Streamable] = None
            if src.kind == uint8(SigningDataKind.FOLIAGE_BLOCK_DATA):
                data = FoliageBlockData.from_bytes(src.data)
                assert (
                    data.farmer_reward_puzzle_hash == farmer_reward_address
                    or data.farmer_reward_puzzle_hash
                    == bytes32(full_node_2.constants.GENESIS_PRE_FARM_FARMER_PUZZLE_HASH)
                )
                if data.farmer_reward_puzzle_hash == farmer_reward_address:
                    validated_foliage_data = True
            elif src.kind == uint8(SigningDataKind.FOLIAGE_TRANSACTION_BLOCK):
                data = FoliageTransactionBlock.from_bytes(src.data)
                validated_foliage_transaction = True
            elif src.kind == uint8(SigningDataKind.CHALLENGE_CHAIN_VDF):
                data = ClassgroupElement.from_bytes(src.data)
                validated_cc_vdf = True
            elif src.kind == uint8(SigningDataKind.REWARD_CHAIN_VDF):
                data = ClassgroupElement.from_bytes(src.data)
                validated_rc_vdf = True
            elif src.kind == uint8(SigningDataKind.CHALLENGE_CHAIN_SUB_SLOT):
                data = ChallengeChainSubSlot.from_bytes(src.data)
                validated_sub_slot_cc = True
            elif src.kind == uint8(SigningDataKind.REWARD_CHAIN_SUB_SLOT):
                data = RewardChainSubSlot.from_bytes(src.data)
                validated_sub_slot_rc = True
            elif src.kind == uint8(SigningDataKind.PARTIAL):
                # #NOTE: This data type is difficult to trigger, so it is
                #        not tested for the time being.
                # data = PostPartialPayload.from_bytes(src.data)
                # validated_partial = True
                pass

            finished_validating_data = (
                validated_foliage_data
                and validated_foliage_transaction
                and validated_cc_vdf
                and validated_rc_vdf
                and validated_sub_slot_cc
                and validated_sub_slot_rc
            )

            assert data is not None
            data_hash = data.get_hash()
            assert data_hash == hash

    async def intercept_farmer_new_proof_of_space(*args: Any) -> None:
        nonlocal farmer
        nonlocal farmer_reward_address

        request: harvester_protocol.NewProofOfSpace = dataclasses.replace(
            harvester_protocol.NewProofOfSpace.from_bytes(args[0]), farmer_reward_address_override=farmer_reward_address
        )
        peer: WSChiaConnection = args[1]

        await FarmerAPI.new_proof_of_space(farmer.server.api, request, peer)

    async def intercept_farmer_request_signed_values(*args: Any) -> Optional[Message]:
        nonlocal farmer
        nonlocal farmer_reward_address
        nonlocal full_node_2

        request: RequestSignedValues = RequestSignedValues.from_bytes(args[0])

        # Ensure the FullNode included the source data for the signatures
        assert request.foliage_block_data
        assert request.foliage_block_data.get_hash() == request.foliage_block_data_hash
        assert request.foliage_transaction_block_data
        assert request.foliage_transaction_block_data.get_hash() == request.foliage_transaction_block_hash

        assert (
            request.foliage_block_data.farmer_reward_puzzle_hash == farmer_reward_address
            or request.foliage_block_data.farmer_reward_puzzle_hash
            == bytes32(full_node_2.constants.GENESIS_PRE_FARM_FARMER_PUZZLE_HASH)
        )

        return await FarmerAPI.request_signed_values(farmer.server.api, request)

    mocker.patch.object(farmer.server.api, "request_signed_values", side_effect=intercept_farmer_request_signed_values)
    mocker.patch.object(farmer.server.api, "new_proof_of_space", side_effect=intercept_farmer_new_proof_of_space)
    mocker.patch.object(harvester.server.api, "request_signatures", side_effect=intercept_harvester_request_signatures)


    # Start injecting signage points
    full_node_2_peer_1 = [n for n in list(full_node_2.server.all_connections.values()) if n.local_type == NodeType.FULL_NODE][0]

    for i, sp in enumerate(signage_points):
        is_subslot: bool = isinstance(sp, timelord_protocol.NewEndOfSubSlotVDF)

        if is_subslot:
            full_node_1.log.info(f"Injecting SP for end of sub-slot @ {i}")

            req = full_node_protocol.RespondEndOfSubSlot(sp.end_of_sub_slot_bundle)
            await full_node_2.server.api.respond_end_of_sub_slot(req, full_node_2_peer_1)
        else:
            full_node_1.log.info(f"Injecting SP @ {i}: index: {sp.index_from_challenge}")

            req = full_node_protocol.RespondSignagePoint(
                sp.index_from_challenge,
                sp.challenge_chain_sp_vdf,
                sp.challenge_chain_sp_proof,
                sp.reward_chain_sp_vdf,
                sp.reward_chain_sp_proof,
            )

            await full_node_2.server.api.respond_signage_point(req, full_node_2_peer_1)


    # Wait until test finishes
    def did_finished_validating_data() -> bool:
        return finished_validating_data

    await time_out_assert(60*60, did_finished_validating_data, True)

@pytest.mark.anyio
async def test_harvester_fee_convention(
    farmer_harvester_2_simulators_zero_bits_plot_filter:
    Tuple[
        Service[Farmer, FarmerAPI],
        Service[Harvester, HarvesterAPI],
        Union[Service[FullNode, FullNodeAPI], Service[FullNode, FullNodeSimulator]],
        Union[Service[FullNode, FullNodeAPI], Service[FullNode, FullNodeSimulator]],
        BlockTools,
    ],
    caplog: pytest.LogCaptureFixture,
    mocker: MockerFixture,
) -> None:
    """
    Tests fee convention specified in CHIP-22: https://github.com/Chia-Network/chips/pull/88
    """
    (
        farmer_service,
        _,
        full_node_service_1,
        full_node_service_2,
        _,
    ) = farmer_harvester_2_simulators_zero_bits_plot_filter

    farmer: Farmer = farmer_service._node
    full_node_1: FullNode = full_node_service_1._node
    full_node_2: FullNode = full_node_service_2._node

    # Connect peers to each other
    farmer_service.add_peer(
        UnresolvedPeerInfo(str(full_node_service_2.self_hostname), full_node_service_2._server.get_port())
    )
    full_node_service_2.add_peer(
        UnresolvedPeerInfo(str(full_node_service_1.self_hostname), full_node_service_1._server.get_port())
    )

    await wait_until_node_type_connected(farmer.server, NodeType.FULL_NODE)
    await wait_until_node_type_connected(farmer.server, NodeType.HARVESTER)         # Should already be connected
    await wait_until_node_type_connected(full_node_1.server, NodeType.FULL_NODE)


    fee_threshold = 0.5
    max_fee_proofs = 5
    fee_count = 0
    proof_count = 0

    farmer_reward_puzzle_hash = decode_puzzle_hash("txch1psqeaw0h244v5sy2r4se8pheyl62n8778zl6t5e7dep0xch9xfkqhx2mej")

    async def intercept_farmer_new_proof_of_space(*args: Any) -> None:
        nonlocal farmer
        nonlocal fee_threshold
        nonlocal max_fee_proofs
        nonlocal proof_count
        nonlocal fee_count
        nonlocal farmer_reward_puzzle_hash

        request: harvester_protocol.NewProofOfSpace = harvester_protocol.NewProofOfSpace.from_bytes(args[0])

        fee_threshold_int = uint32(int(0xFFFFFFFF * fee_threshold))

        fee_quality = calculate_harvester_fee_quality(request.proof.proof, request.challenge_hash)
        if fee_quality <= fee_threshold_int and fee_count < max_fee_proofs:
            fee_count += 1
            request = dataclasses.replace(
                request,
                farmer_reward_address_override=farmer_reward_puzzle_hash,
                fee_info=ProofOfSpaceFeeInfo(applied_fee_threshold=fee_threshold_int),
            )

        if proof_count <= max_fee_proofs:
            proof_count += 1

        peer: WSChiaConnection = args[1]
        await FarmerAPI.new_proof_of_space(farmer.server.api, request, peer)

    mocker.patch.object(farmer.server.api, "new_proof_of_space", side_effect=intercept_farmer_new_proof_of_space)


    log_text_len = 0

    def log_has_new_text() -> bool:
        nonlocal caplog
        nonlocal log_text_len

        text_len = len(caplog.text)
        if text_len > log_text_len:
            log_text_len = text_len
            return True

        return False


    # Load test data
    blocks: List[FullBlock]
    signage_points: SPList

    (blocks, signage_points) = load_test_data()
    assert len(blocks) == 1
    await add_test_blocks_into_full_node(blocks, full_node_2)


    # Inject signage points
    full_node_2_peer_1 = [n for n in list(full_node_2.server.all_connections.values()) if n.local_type == NodeType.FULL_NODE][0]

    for i, sp in enumerate(signage_points):
        is_subslot: bool = isinstance(sp, timelord_protocol.NewEndOfSubSlotVDF)

        if is_subslot:
            full_node_1.log.info(f"Injecting SP for end of sub-slot @ {i}")

            req = full_node_protocol.RespondEndOfSubSlot(sp.end_of_sub_slot_bundle)
            await full_node_2.server.api.respond_end_of_sub_slot(req, full_node_2_peer_1)
        else:
            full_node_1.log.info(f"Injecting SP @ {i}: index: {sp.index_from_challenge}")

            req = full_node_protocol.RespondSignagePoint(
                sp.index_from_challenge,
                sp.challenge_chain_sp_vdf,
                sp.challenge_chain_sp_proof,
                sp.reward_chain_sp_vdf,
                sp.reward_chain_sp_proof,
            )

            await full_node_2.server.api.respond_signage_point(req, full_node_2_peer_1)

    # Wait until we've received all the proofs
    def received_all_proofs() -> bool:
        nonlocal max_fee_proofs
        nonlocal fee_count

        return fee_count >= max_fee_proofs

    await time_out_assert(60*60, received_all_proofs, True)

    # Wait for the farmer to pick up the last proofs
    await asyncio.sleep(2)

    assert fee_count > 0
    await time_out_assert(60, log_has_new_text, True)

    find_message = "Fee threshold passed for challenge"
    find_index = 0
    log_text = caplog.text
    fail_count = 0

    for _ in range(fee_count):
        index = log_text.find(find_message, find_index) + len(find_message)
        if index < 0:
            fail_count += 1
            assert fail_count < 10
            await time_out_assert(10, log_has_new_text, True)
            log_text = caplog.text
        else:
            find_index = index


async def wait_until_node_type_connected(server: ChiaServer, node_type: NodeType) -> WSChiaConnection:
    while True:
        for peer in server.all_connections.values():
            if peer.connection_type == node_type.value:
                return peer
        await asyncio.sleep(1)


def decode_sp(is_sub_slot: bool, sp64: str) -> Union[timelord_protocol.NewEndOfSubSlotVDF,timelord_protocol.NewSignagePointVDF]:
    sp_bytes = base64.b64decode(sp64)
    if is_sub_slot:
        return timelord_protocol.NewEndOfSubSlotVDF.from_bytes(sp_bytes)
    
    return timelord_protocol.NewSignagePointVDF.from_bytes(sp_bytes)

def load_test_data():
    # with open('sp_data64.json', 'r') as f:
    #     data = json.load(f)
    data = test_data
    blocks = [FullBlock.from_bytes(base64.b64decode(data["block"]))]
    signage_points = [decode_sp(sp[0], sp[1]) for sp in data["signage_points"]]
    return (blocks, signage_points)

async def add_test_blocks_into_full_node(blocks: List[FullBlock], full_node: FullNode) -> None:

    # Inject full node with a pre-existing block to skip initial genesis sub-slot
    # so that we have blocks generated that have our farmer reward address, instead
    # of the GENESIS_PRE_FARM_FARMER_PUZZLE_HASH.
    pre_validation_results: List[PreValidationResult] = await full_node.blockchain.pre_validate_blocks_multiprocessing(
        blocks, {}, validate_signatures=True
    )
    assert pre_validation_results is not None and len(pre_validation_results) == len(blocks)
    for i in range(len(blocks)):
        r, _, _ = await full_node.blockchain.add_block(blocks[i], pre_validation_results[i])
        assert r == AddBlockResult.NEW_PEAK
