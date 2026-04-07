from __future__ import annotations

import pytest
from chia_rs import ConsensusConstants, FullBlock, HeaderBlock
from chia_rs.sized_ints import uint8, uint32, uint64

from chia._tests.conftest import ConsensusMode
from chia._tests.util.db_connection import DBConnection
from chia._tests.util.setup_nodes import OldSimulatorsAndWallets
from chia.consensus.blockchain import AddBlockResult
from chia.consensus.generator_tools import get_block_header
from chia.protocols import full_node_protocol
from chia.simulator.add_blocks_in_batches import add_blocks_in_batches
from chia.types.blockchain_format.vdf import VDFProof
from chia.wallet.key_val_store import KeyValStore
from chia.wallet.wallet_blockchain import WalletBlockchain


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.HARD_FORK_2_0])
@pytest.mark.anyio
@pytest.mark.standard_block_tools
async def test_wallet_blockchain(
    simulator_and_wallet: OldSimulatorsAndWallets, default_1000_blocks: list[FullBlock]
) -> None:
    [full_node_api], [(wallet_node, _)], bt = simulator_and_wallet

    await add_blocks_in_batches(default_1000_blocks[:700], full_node_api.full_node)
    resp = await full_node_api.request_proof_of_weight(
        full_node_protocol.RequestProofOfWeight(
            uint32(default_1000_blocks[599].height + 1), default_1000_blocks[599].header_hash
        )
    )
    assert resp is not None
    resp_2 = await full_node_api.request_proof_of_weight(
        full_node_protocol.RequestProofOfWeight(
            uint32(default_1000_blocks[560].height + 1), default_1000_blocks[560].header_hash
        )
    )
    assert resp_2 is not None
    resp_3 = await full_node_api.request_proof_of_weight(
        full_node_protocol.RequestProofOfWeight(
            uint32(default_1000_blocks[605].height + 1), default_1000_blocks[605].header_hash
        )
    )
    assert resp_3 is not None
    weight_proof = full_node_protocol.RespondProofOfWeight.from_bytes(resp.data).wp
    assert wallet_node._weight_proof_handler is not None
    records = await wallet_node._weight_proof_handler.validate_weight_proof(weight_proof, True)
    weight_proof_short = full_node_protocol.RespondProofOfWeight.from_bytes(resp_2.data).wp
    records_short = await wallet_node._weight_proof_handler.validate_weight_proof(weight_proof_short, True)
    weight_proof_long = full_node_protocol.RespondProofOfWeight.from_bytes(resp_3.data).wp
    records_long = await wallet_node._weight_proof_handler.validate_weight_proof(weight_proof_long, True)

    async with DBConnection(1) as db_wrapper:
        store = await KeyValStore.create(db_wrapper)
        chain = await WalletBlockchain.create(store, bt.constants)

        assert (await chain.get_peak_block()) is None
        assert chain.get_latest_timestamp() == 0

        await chain.new_valid_weight_proof(weight_proof, records)
        peak_block = await chain.get_peak_block()
        assert peak_block is not None
        assert peak_block.height == 599
        assert chain.get_latest_timestamp() > 0

        await chain.new_valid_weight_proof(weight_proof_short, records_short)
        peak_block = await chain.get_peak_block()
        assert peak_block is not None
        assert peak_block.height == 599

        await chain.new_valid_weight_proof(weight_proof_long, records_long)
        peak_block = await chain.get_peak_block()
        assert peak_block is not None
        assert peak_block.height == 605

        header_blocks: list[HeaderBlock] = []
        for block in default_1000_blocks:
            header_block = get_block_header(block)
            header_blocks.append(header_block)

        res, err = await chain.add_block(header_blocks[50])
        print(res, err)
        assert res == AddBlockResult.DISCONNECTED_BLOCK

        res, err = await chain.add_block(header_blocks[500])
        print(res, err)
        assert res == AddBlockResult.ALREADY_HAVE_BLOCK

        res, err = await chain.add_block(header_blocks[607])
        print(res, err)
        assert res == AddBlockResult.DISCONNECTED_BLOCK

        res, err = await chain.add_block(
            header_blocks[606].replace(challenge_chain_ip_proof=VDFProof(uint8(2), b"123", True))
        )
        assert res == AddBlockResult.INVALID_BLOCK

        peak_block = await chain.get_peak_block()
        assert peak_block is not None
        assert peak_block.height == 605

        for header_block in header_blocks[606:]:
            res, err = await chain.add_block(header_block)
            assert res == AddBlockResult.NEW_PEAK
            peak_block = await chain.get_peak_block()
            assert peak_block is not None
            assert peak_block.height == header_block.height

        peak_block = await chain.get_peak_block()
        assert peak_block is not None
        assert peak_block.height == 999


@pytest.mark.anyio
async def test_wallet_blockchain_create_uses_persisted_values(blockchain_constants: ConsensusConstants) -> None:
    async with DBConnection(1) as db_wrapper:
        store = await KeyValStore.create(db_wrapper)
        sub_slot_iters = uint64(42)
        difficulty = uint64(1337)
        await store.set_object("SUB_SLOT_ITERS", sub_slot_iters)
        await store.set_object("DIFFICULTY", difficulty)

        chain = await WalletBlockchain.create(store, blockchain_constants)
        assert chain._sub_slot_iters == sub_slot_iters
        assert chain._difficulty == difficulty


@pytest.mark.anyio
async def test_wallet_blockchain_create_defaults_without_persisted_values(
    blockchain_constants: ConsensusConstants,
) -> None:
    async with DBConnection(1) as db_wrapper:
        store = await KeyValStore.create(db_wrapper)
        chain = await WalletBlockchain.create(store, blockchain_constants)

        assert chain._sub_slot_iters == blockchain_constants.SUB_SLOT_ITERS_STARTING
        assert chain._difficulty == blockchain_constants.DIFFICULTY_STARTING
