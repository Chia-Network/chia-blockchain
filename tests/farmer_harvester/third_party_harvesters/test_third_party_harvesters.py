from __future__ import annotations

import asyncio
import dataclasses
from typing import Any, List, Optional, Tuple, Union, cast

import pytest
from pytest_mock import MockerFixture

from chia.farmer.farmer import Farmer, calculate_harvester_fee_quality
from chia.farmer.farmer_api import FarmerAPI
from chia.full_node.full_node import FullNode
from chia.full_node.full_node_api import FullNodeAPI
from chia.harvester.harvester import Harvester
from chia.harvester.harvester_api import HarvesterAPI
from chia.protocols import harvester_protocol
from chia.protocols.farmer_protocol import RequestSignedValues
from chia.protocols.harvester_protocol import ProofOfSpaceFeeInfo, RespondSignatures, SigningDataKind
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.outbound_message import Message, NodeType, make_msg
from chia.server.server import ChiaServer
from chia.server.start_service import Service
from chia.server.ws_connection import WSChiaConnection
from chia.simulator.block_tools import BlockTools
from chia.simulator.full_node_simulator import FullNodeSimulator
from chia.timelord.timelord import Timelord
from chia.timelord.timelord_api import TimelordAPI
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.blockchain_format.foliage import FoliageBlockData, FoliageTransactionBlock
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.blockchain_format.slots import ChallengeChainSubSlot, RewardChainSubSlot
from chia.types.peer_info import UnresolvedPeerInfo
from chia.util.bech32m import decode_puzzle_hash
from chia.util.ints import uint8, uint32
from chia.util.streamable import Streamable
from tests.util.time_out_assert import time_out_assert


@pytest.mark.anyio
async def test_harvester_receive_source_signing_data(
    farmer_harvester_full_node_timelord_zero_bits_plot_filter: Tuple[
        Service[Harvester, HarvesterAPI],
        Service[Farmer, FarmerAPI],
        Union[Service[FullNode, FullNodeAPI], Service[FullNode, FullNodeSimulator]],
        Service[Timelord, TimelordAPI],
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
        harvester_service,
        farmer_service,
        full_node_service_1,
        _,
        _,
    ) = farmer_harvester_full_node_timelord_zero_bits_plot_filter

    farmer: Farmer = farmer_service._node
    harvester: Harvester = harvester_service._node
    full_node: FullNode = full_node_service_1._node

    # Connect peers to each other
    farmer_service.add_peer(
        UnresolvedPeerInfo(str(full_node_service_1.self_hostname), full_node_service_1._server.get_port())
    )
    harvester_service.add_peer(UnresolvedPeerInfo(str(farmer_service.self_hostname), farmer_service._server.get_port()))

    validated_foliage_data = False
    validated_foliage_transaction = False
    validated_cc_vdf = False
    validated_rc_vdf = False
    validated_sub_slot_cc = False
    validated_sub_slot_rc = False
    # validated_partial = False

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
        nonlocal full_node
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

        for i in range(len(request.messages)):
            hash = request.messages[i]
            src = request.message_data[i]
            assert src

            data: Optional[Streamable] = None
            if src.kind == uint8(SigningDataKind.FOLIAGE_BLOCK_DATA):
                data = FoliageBlockData.from_bytes(src.data)
                assert (
                    data.farmer_reward_puzzle_hash == farmer_reward_address
                    or data.farmer_reward_puzzle_hash
                    == bytes32(full_node.constants.GENESIS_PRE_FARM_FARMER_PUZZLE_HASH)
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
        nonlocal full_node

        request: RequestSignedValues = RequestSignedValues.from_bytes(args[0])

        # Ensure the FullNode included the source data for the signatures
        assert request.foliage_block_data
        assert request.foliage_block_data.get_hash() == request.foliage_block_data_hash
        assert request.foliage_transaction_block_data
        assert request.foliage_transaction_block_data.get_hash() == request.foliage_transaction_block_hash

        assert (
            request.foliage_block_data.farmer_reward_puzzle_hash == farmer_reward_address
            or request.foliage_block_data.farmer_reward_puzzle_hash
            == bytes32(full_node.constants.GENESIS_PRE_FARM_FARMER_PUZZLE_HASH)
        )

        return await FarmerAPI.request_signed_values(farmer.server.api, request)

    mocker.patch.object(farmer.server.api, "request_signed_values", side_effect=intercept_farmer_request_signed_values)
    mocker.patch.object(farmer.server.api, "new_proof_of_space", side_effect=intercept_farmer_new_proof_of_space)
    mocker.patch.object(harvester.server.api, "request_signatures", side_effect=intercept_harvester_request_signatures)

    await wait_until_node_type_connected(farmer.server, NodeType.FULL_NODE)
    await wait_until_node_type_connected(farmer.server, NodeType.HARVESTER)

    # wait until test finishes
    def did_finished_validating_data() -> bool:
        return finished_validating_data

    await time_out_assert(90, did_finished_validating_data, True)


@pytest.mark.anyio
async def test_harvester_fee_convention(
    farmer_harvester_full_node_timelord_zero_bits_plot_filter: Tuple[
        Service[Harvester, HarvesterAPI],
        Service[Farmer, FarmerAPI],
        Union[Service[FullNode, FullNodeAPI], Service[FullNode, FullNodeSimulator]],
        Service[Timelord, TimelordAPI],
        BlockTools,
    ],
    caplog: pytest.LogCaptureFixture,
    mocker: MockerFixture,
) -> None:
    """
    Tests fee convention specified in CHIP-22: https://github.com/Chia-Network/chips/pull/88
    """
    (
        harvester_service,
        farmer_service,
        full_node_service_1,
        _,
        _,
    ) = farmer_harvester_full_node_timelord_zero_bits_plot_filter

    farmer: Farmer = farmer_service._node

    # Connect peers to each other
    farmer_service.add_peer(
        UnresolvedPeerInfo(str(full_node_service_1.self_hostname), full_node_service_1._server.get_port())
    )
    harvester_service.add_peer(UnresolvedPeerInfo(str(farmer_service.self_hostname), farmer_service._server.get_port()))

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

    await wait_until_node_type_connected(farmer.server, NodeType.FULL_NODE)
    await wait_until_node_type_connected(farmer.server, NodeType.HARVESTER)

    log_text_len = 0

    def log_has_new_text() -> bool:
        nonlocal log_text_len

        text_len = len(caplog.text)
        if text_len > log_text_len:
            log_text_len = text_len
            return True

        return False

    # wait until we've received all the proofs
    def received_all_proofs() -> bool:
        nonlocal max_fee_proofs
        nonlocal fee_count

        return fee_count >= max_fee_proofs

    await time_out_assert(120, received_all_proofs, True)

    # Wait for the farmer to pick up the last proofs
    await asyncio.sleep(2)

    assert fee_count > 0
    await time_out_assert(10, log_has_new_text, True)

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
        else:
            find_index = index


async def wait_until_node_type_connected(server: ChiaServer, node_type: NodeType) -> WSChiaConnection:
    while True:
        for peer in server.all_connections.values():
            if peer.connection_type == node_type.value:
                return peer
        await asyncio.sleep(1)
