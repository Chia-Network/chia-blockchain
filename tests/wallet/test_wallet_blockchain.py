from __future__ import annotations

import dataclasses
from typing import List

import pytest

from chia.consensus.blockchain import AddBlockResult
from chia.protocols import full_node_protocol
from chia.types.blockchain_format.vdf import VDFProof
from chia.types.full_block import FullBlock
from chia.types.header_block import HeaderBlock
from chia.util.generator_tools import get_block_header
from chia.util.ints import uint8, uint32
from chia.wallet.key_val_store import KeyValStore
from chia.wallet.wallet_blockchain import WalletBlockchain
from tests.conftest import ConsensusMode
from tests.util.db_connection import DBConnection
from tests.util.setup_nodes import OldSimulatorsAndWallets


@pytest.mark.limit_consensus_modes(allowed=[ConsensusMode.PLAIN, ConsensusMode.HARD_FORK_2_0], reason="save time")
@pytest.mark.anyio
async def test_wallet_blockchain(
    simulator_and_wallet: OldSimulatorsAndWallets, default_1000_blocks: List[FullBlock]
) -> None:
    [full_node_api], [(wallet_node, _)], bt = simulator_and_wallet

    for block in default_1000_blocks[:600]:
        await full_node_api.full_node.add_block(block)

    resp = await full_node_api.request_proof_of_weight(
        full_node_protocol.RequestProofOfWeight(
            uint32(default_1000_blocks[499].height + 1), default_1000_blocks[499].header_hash
        )
    )
    assert resp is not None
    resp_2 = await full_node_api.request_proof_of_weight(
        full_node_protocol.RequestProofOfWeight(
            uint32(default_1000_blocks[460].height + 1), default_1000_blocks[460].header_hash
        )
    )
    assert resp_2 is not None
    resp_3 = await full_node_api.request_proof_of_weight(
        full_node_protocol.RequestProofOfWeight(
            uint32(default_1000_blocks[505].height + 1), default_1000_blocks[505].header_hash
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
        assert peak_block.height == 499
        assert chain.get_latest_timestamp() > 0

        await chain.new_valid_weight_proof(weight_proof_short, records_short)
        peak_block = await chain.get_peak_block()
        assert peak_block is not None
        assert peak_block.height == 499

        await chain.new_valid_weight_proof(weight_proof_long, records_long)
        peak_block = await chain.get_peak_block()
        assert peak_block is not None
        assert peak_block.height == 505

        header_blocks: List[HeaderBlock] = []
        for block in default_1000_blocks:
            header_block = get_block_header(block, [], [])
            header_blocks.append(header_block)

        res, err = await chain.add_block(header_blocks[50])
        print(res, err)
        assert res == AddBlockResult.DISCONNECTED_BLOCK

        res, err = await chain.add_block(header_blocks[400])
        print(res, err)
        assert res == AddBlockResult.ALREADY_HAVE_BLOCK

        res, err = await chain.add_block(header_blocks[507])
        print(res, err)
        assert res == AddBlockResult.DISCONNECTED_BLOCK

        res, err = await chain.add_block(
            dataclasses.replace(header_blocks[506], challenge_chain_ip_proof=VDFProof(uint8(2), b"123", True))
        )
        assert res == AddBlockResult.INVALID_BLOCK

        peak_block = await chain.get_peak_block()
        assert peak_block is not None
        assert peak_block.height == 505

        for header_block in header_blocks[506:]:
            res, err = await chain.add_block(header_block)
            assert res == AddBlockResult.NEW_PEAK
            peak_block = await chain.get_peak_block()
            assert peak_block is not None
            assert peak_block.height == header_block.height

        peak_block = await chain.get_peak_block()
        assert peak_block is not None
        assert peak_block.height == 999
