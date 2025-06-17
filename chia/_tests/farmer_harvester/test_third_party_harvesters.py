from __future__ import annotations

import asyncio
import base64
import contextlib
import dataclasses
import json
import logging
from os.path import dirname
from typing import Optional, Union, cast

import pytest
from chia_rs import (
    ChallengeChainSubSlot,
    FoliageBlockData,
    FoliageTransactionBlock,
    FullBlock,
    G1Element,
    ProofOfSpace,
    RewardChainSubSlot,
)
from chia_rs.sized_bytes import bytes32
from chia_rs.sized_ints import uint8, uint32, uint64

from chia._tests.util.misc import patch_request_handler
from chia._tests.util.time_out_assert import time_out_assert
from chia.consensus.augmented_chain import AugmentedBlockchain
from chia.consensus.block_body_validation import ForkInfo
from chia.consensus.blockchain import AddBlockResult
from chia.consensus.difficulty_adjustment import get_next_sub_slot_iters_and_difficulty
from chia.consensus.multiprocess_validation import PreValidationResult, pre_validate_block
from chia.farmer.farmer import Farmer, calculate_harvester_fee_quality
from chia.farmer.farmer_api import FarmerAPI
from chia.full_node.full_node import FullNode
from chia.full_node.full_node_api import FullNodeAPI
from chia.harvester.harvester import Harvester
from chia.harvester.harvester_api import HarvesterAPI
from chia.protocols import farmer_protocol, full_node_protocol, harvester_protocol, timelord_protocol
from chia.protocols.harvester_protocol import ProofOfSpaceFeeInfo, RespondSignatures, SigningDataKind
from chia.protocols.outbound_message import Message, NodeType, make_msg
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.aliases import FarmerService, FullNodeService, HarvesterService
from chia.server.server import ChiaServer
from chia.server.ws_connection import WSChiaConnection
from chia.simulator.block_tools import BlockTools
from chia.simulator.start_simulator import SimulatorFullNodeService
from chia.types.blockchain_format.classgroup import ClassgroupElement
from chia.types.peer_info import UnresolvedPeerInfo
from chia.types.validation_state import ValidationState
from chia.util.bech32m import decode_puzzle_hash
from chia.util.hash import std_hash

SPType = Union[timelord_protocol.NewEndOfSubSlotVDF, timelord_protocol.NewSignagePointVDF]
SPList = list[SPType]


@pytest.mark.anyio
async def test_harvester_receive_source_signing_data(
    farmer_harvester_2_simulators_zero_bits_plot_filter: tuple[
        FarmerService,
        HarvesterService,
        Union[FullNodeService, SimulatorFullNodeService],
        Union[FullNodeService, SimulatorFullNodeService],
        BlockTools,
    ],
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
    await wait_until_node_type_connected(farmer.server, NodeType.HARVESTER)  # Should already be connected
    await wait_until_node_type_connected(full_node_1.server, NodeType.FULL_NODE)

    # Prepare test data
    blocks: list[FullBlock]
    signage_points: SPList

    (blocks, signage_points) = load_test_data()
    assert len(blocks) == 1

    # Inject full node with a pre-existing block to skip initial genesis sub-slot
    # so that we have blocks generated that have our farmer reward address, instead
    # of the GENESIS_PRE_FARM_FARMER_PUZZLE_HASH.
    await add_test_blocks_into_full_node(blocks, full_node_2)
    await time_out_assert(60, full_node_2.blockchain.get_peak_height, blocks[-1].height)

    validated_foliage_data = False
    validated_foliage_transaction = False
    validated_cc_vdf = False
    validated_rc_vdf = False
    validated_sub_slot_cc = False
    validated_sub_slot_rc = False
    # validated_partial = False     # Not covered currently. See comment in validate_harvester_request_signatures

    finished_validating_data = False
    farmer_reward_address = decode_puzzle_hash("txch1psqeaw0h244v5sy2r4se8pheyl62n8778zl6t5e7dep0xch9xfkqhx2mej")

    async def intercept_harvester_request_signatures(
        self: HarvesterAPI, request: harvester_protocol.RequestSignatures
    ) -> Optional[Message]:
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
        nonlocal farmer
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

            data: Optional[
                Union[
                    FoliageBlockData,
                    FoliageTransactionBlock,
                    ClassgroupElement,
                    ChallengeChainSubSlot,
                    RewardChainSubSlot,
                ]
            ] = None
            if src.kind == uint8(SigningDataKind.FOLIAGE_BLOCK_DATA):
                data = FoliageBlockData.from_bytes(src.data)
                assert (
                    data.farmer_reward_puzzle_hash == farmer_reward_address
                    or data.farmer_reward_puzzle_hash
                    == bytes32(full_node_2.constants.GENESIS_PRE_FARM_FARMER_PUZZLE_HASH)
                )
                # RC block unfinished must always be present when foliage block data is present
                assert request.rc_block_unfinished
                assert request.rc_block_unfinished.get_hash() == data.unfinished_reward_block_hash

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
            # #NOTE: This data type is difficult to trigger, so it is
            #        not tested for the time being.
            # data = PostPartialPayload.from_bytes(src.data)
            # validated_partial = True
            # elif src.kind == uint8(SigningDataKind.PARTIAL):
            #     pass

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

    async def intercept_farmer_new_proof_of_space(
        self: HarvesterAPI, request: harvester_protocol.NewProofOfSpace, peer: WSChiaConnection
    ) -> None:
        nonlocal farmer
        nonlocal farmer_reward_address

        request = dataclasses.replace(request, farmer_reward_address_override=farmer_reward_address)

        await FarmerAPI.new_proof_of_space(farmer.server.api, request, peer)

    async def intercept_farmer_request_signed_values(
        self: FarmerAPI, request: farmer_protocol.RequestSignedValues
    ) -> Optional[Message]:
        nonlocal farmer
        nonlocal farmer_reward_address
        nonlocal full_node_2

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

    with contextlib.ExitStack() as exit_stack:
        exit_stack.enter_context(
            patch_request_handler(
                api=farmer.server.api,
                handler=intercept_farmer_request_signed_values,
                request_type=ProtocolMessageTypes.request_signed_values,
            )
        )
        exit_stack.enter_context(
            patch_request_handler(
                api=farmer.server.api,
                handler=intercept_farmer_new_proof_of_space,
                request_type=ProtocolMessageTypes.new_proof_of_space,
            )
        )
        exit_stack.enter_context(
            patch_request_handler(
                api=harvester.server.api,
                handler=intercept_harvester_request_signatures,
                request_type=ProtocolMessageTypes.request_signatures,
            )
        )

        # Start injecting signage points
        await inject_signage_points(signage_points, full_node_1, full_node_2)

        # Wait until test finishes
        def did_finished_validating_data() -> bool:
            return finished_validating_data

        await time_out_assert(60, did_finished_validating_data, True)


@pytest.mark.anyio
async def test_harvester_fee_convention(
    farmer_harvester_2_simulators_zero_bits_plot_filter: tuple[
        FarmerService,
        HarvesterService,
        Union[FullNodeService, SimulatorFullNodeService],
        Union[FullNodeService, SimulatorFullNodeService],
        BlockTools,
    ],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Tests fee convention specified in CHIP-22: https://github.com/Chia-Network/chips/pull/88
    """
    (
        farmer_service,
        _,
        _,
        _,
        _,
    ) = farmer_harvester_2_simulators_zero_bits_plot_filter

    caplog.set_level(logging.DEBUG)
    farmer: Farmer = farmer_service._node
    (sp, pos) = prepare_sp_and_pos_for_fee_test(1)
    farmer.notify_farmer_reward_taken_by_harvester_as_fee(sp, pos)

    assert await scan_log_for_message(caplog, "Fee threshold passed for challenge")


@pytest.mark.anyio
async def test_harvester_fee_invalid_convention(
    farmer_harvester_2_simulators_zero_bits_plot_filter: tuple[
        FarmerService,
        HarvesterService,
        Union[FullNodeService, SimulatorFullNodeService],
        Union[FullNodeService, SimulatorFullNodeService],
        BlockTools,
    ],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Tests that logs are properly emitted when an invalid free threshold is specified
    given the fee convention from CHIP-22: https://github.com/Chia-Network/chips/pull/88
    """
    (
        farmer_service,
        _,
        _,
        _,
        _,
    ) = farmer_harvester_2_simulators_zero_bits_plot_filter

    farmer: Farmer = farmer_service._node
    caplog.set_level(logging.DEBUG)

    (sp, pos) = prepare_sp_and_pos_for_fee_test(-1)
    farmer.notify_farmer_reward_taken_by_harvester_as_fee(sp, pos)
    farmer.log.propagate

    assert await scan_log_for_message(caplog, "Invalid fee threshold for challenge")


def prepare_sp_and_pos_for_fee_test(
    fee_threshold_offset: int,
) -> tuple[farmer_protocol.NewSignagePoint, harvester_protocol.NewProofOfSpace]:
    proof = std_hash(b"1")
    challenge = std_hash(b"1")

    fee_quality = calculate_harvester_fee_quality(proof, challenge)

    pubkey = G1Element.from_bytes(
        bytes.fromhex(
            "80a836a74b077cabaca7a76d1c3c9f269f7f3a8f2fa196a65ee8953eb81274eb8b7328d474982617af5a0fe71b47e9b8"
        )
    )

    # Send some fake data to the framer
    sp = farmer_protocol.NewSignagePoint(
        challenge_hash=challenge,
        challenge_chain_sp=challenge,
        reward_chain_sp=challenge,
        difficulty=uint64(0),
        sub_slot_iters=uint64(0),
        signage_point_index=uint8(0),
        peak_height=uint32(1),
        last_tx_height=uint32(0),
    )

    pos = harvester_protocol.NewProofOfSpace(
        challenge_hash=challenge,
        sp_hash=challenge,
        plot_identifier="foo.plot",
        proof=ProofOfSpace(
            challenge=challenge,
            pool_public_key=None,
            pool_contract_puzzle_hash=None,
            plot_public_key=pubkey,
            version_and_size=uint8(32),
            proof=proof,
        ),
        signage_point_index=uint8(0),
        include_source_signature_data=False,
        farmer_reward_address_override=decode_puzzle_hash(
            "txch1psqeaw0h244v5sy2r4se8pheyl62n8778zl6t5e7dep0xch9xfkqhx2mej"
        ),
        fee_info=ProofOfSpaceFeeInfo(
            # Apply threshold offset to make the fee either pass or fail
            applied_fee_threshold=uint32(fee_quality + fee_threshold_offset)
        ),
    )

    return (sp, pos)


async def scan_log_for_message(caplog: pytest.LogCaptureFixture, find_message: str) -> bool:  # pragma: no cover
    log_text_len = 0

    def log_has_new_text() -> bool:
        nonlocal caplog
        nonlocal log_text_len

        text_len = len(caplog.text)
        if text_len > log_text_len:
            log_text_len = text_len
            return True

        return False

    await time_out_assert(60, log_has_new_text, True)

    log_text = caplog.text
    find_index = 0
    fail_count = 0
    max_fails = 10

    for _ in range(max_fails):
        index = log_text.find(find_message, find_index)
        if index >= 0:
            return True

        fail_count += 1
        assert fail_count < max_fails
        await time_out_assert(10, log_has_new_text, True)
        log_text = caplog.text

    return False


async def wait_until_node_type_connected(server: ChiaServer, node_type: NodeType) -> WSChiaConnection:
    while True:
        for peer in server.all_connections.values():
            if peer.connection_type == node_type.value:
                return peer
        await asyncio.sleep(1)


def decode_sp(
    is_sub_slot: bool, sp64: str
) -> Union[timelord_protocol.NewEndOfSubSlotVDF, timelord_protocol.NewSignagePointVDF]:
    sp_bytes = base64.b64decode(sp64)
    if is_sub_slot:
        return timelord_protocol.NewEndOfSubSlotVDF.from_bytes(sp_bytes)

    return timelord_protocol.NewSignagePointVDF.from_bytes(sp_bytes)


async def add_test_blocks_into_full_node(blocks: list[FullBlock], full_node: FullNode) -> None:
    # Inject full node with a pre-existing block to skip initial genesis sub-slot
    # so that we have blocks generated that have our farmer reward address, instead
    # of the GENESIS_PRE_FARM_FARMER_PUZZLE_HASH.
    prev_b = None
    block = blocks[0]
    prev_ses_block = None
    if block.height > 0:  # pragma: no cover
        prev_b = await full_node.blockchain.get_block_record_from_db(block.prev_header_hash)
        assert prev_b is not None
        curr = prev_b
        while curr.height > 0 and curr.sub_epoch_summary_included is None:
            curr = full_node.blockchain.block_record(curr.prev_hash)
        prev_ses_block = curr
    new_slot = len(block.finished_sub_slots) > 0
    ssi, diff = get_next_sub_slot_iters_and_difficulty(full_node.constants, new_slot, prev_b, full_node.blockchain)
    futures = []
    chain = AugmentedBlockchain(full_node.blockchain)
    for block in blocks:
        futures.append(
            await pre_validate_block(
                full_node.blockchain.constants,
                chain,
                block,
                full_node.blockchain.pool,
                None,
                ValidationState(ssi, diff, prev_ses_block),
            )
        )
    pre_validation_results: list[PreValidationResult] = list(await asyncio.gather(*futures))
    assert pre_validation_results is not None and len(pre_validation_results) == len(blocks)
    for i in range(len(blocks)):
        block = blocks[i]
        if block.height != 0 and len(block.finished_sub_slots) > 0:  # pragma: no cover
            if block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters is not None:
                ssi = block.finished_sub_slots[0].challenge_chain.new_sub_slot_iters
        fork_info = ForkInfo(block.height - 1, block.height - 1, block.prev_header_hash)
        r, _, _ = await full_node.blockchain.add_block(
            blocks[i], pre_validation_results[i], sub_slot_iters=ssi, fork_info=fork_info
        )
        assert r == AddBlockResult.NEW_PEAK


async def inject_signage_points(signage_points: SPList, full_node_1: FullNode, full_node_2: FullNode) -> None:
    full_node_2_peer_1 = next(
        n for n in list(full_node_2.server.all_connections.values()) if n.local_type == NodeType.FULL_NODE
    )

    api2 = cast(FullNodeAPI, full_node_2.server.api)

    for i, sp in enumerate(signage_points):
        req: Union[full_node_protocol.RespondEndOfSubSlot, full_node_protocol.RespondSignagePoint]

        if isinstance(sp, timelord_protocol.NewEndOfSubSlotVDF):
            full_node_1.log.info(f"Injecting SP for end of sub-slot @ {i}")

            req = full_node_protocol.RespondEndOfSubSlot(sp.end_of_sub_slot_bundle)
            await api2.respond_end_of_sub_slot(req, full_node_2_peer_1)
        else:
            full_node_1.log.info(f"Injecting SP @ {i}: index: {sp.index_from_challenge}")

            req = full_node_protocol.RespondSignagePoint(
                sp.index_from_challenge,
                sp.challenge_chain_sp_vdf,
                sp.challenge_chain_sp_proof,
                sp.reward_chain_sp_vdf,
                sp.reward_chain_sp_proof,
            )

            await api2.respond_signage_point(req, full_node_2_peer_1)


# Pre-generated test signage points encoded as base64.
# Each element contains either a NewSignagePointVDF or a NewEndOfSubSlotVDF.
# If the first element of the tuple is True, then it is as NewEndOfSubSlotVDF.
# A FullBlock is also included which is infused already in the chain so
# that the next NewEndOfSubSlotVDF is valid.
# This block has to be added to the test FullNode before injecting the signage points.
def load_test_data() -> tuple[list[FullBlock], SPList]:
    file_path: str = dirname(__file__) + "/test_third_party_harvesters_data.json"
    with open(file_path) as f:
        data = json.load(f)
        blocks = [FullBlock.from_bytes(base64.b64decode(cast(str, data["block"])))]

        signage_points = [decode_sp(cast(bool, sp[0]), cast(str, sp[1])) for sp in data["signage_points"]]
        return (blocks, signage_points)
