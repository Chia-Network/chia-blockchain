from __future__ import annotations

import dataclasses

import pytest

from chia.consensus.blockchain import ReceiveBlockResult
from chia.protocols import full_node_protocol
from chia.simulator.block_tools import test_constants
from chia.types.blockchain_format.vdf import VDFProof
from chia.types.weight_proof import WeightProof
from chia.util.generator_tools import get_block_header
from chia.wallet.key_val_store import KeyValStore
from chia.wallet.wallet_blockchain import WalletBlockchain
from tests.util.db_connection import DBConnection


class TestWalletBlockchain:
    @pytest.mark.asyncio
    async def test_wallet_blockchain(self, wallet_node, default_1000_blocks):
        full_node_api, wallet_node, full_node_server, wallet_server, _ = wallet_node

        for block in default_1000_blocks[:600]:
            await full_node_api.full_node.respond_block(full_node_protocol.RespondBlock(block))

        res = await full_node_api.request_proof_of_weight(
            full_node_protocol.RequestProofOfWeight(
                default_1000_blocks[499].height + 1, default_1000_blocks[499].header_hash
            )
        )
        res_2 = await full_node_api.request_proof_of_weight(
            full_node_protocol.RequestProofOfWeight(
                default_1000_blocks[460].height + 1, default_1000_blocks[460].header_hash
            )
        )

        res_3 = await full_node_api.request_proof_of_weight(
            full_node_protocol.RequestProofOfWeight(
                default_1000_blocks[505].height + 1, default_1000_blocks[505].header_hash
            )
        )
        weight_proof: WeightProof = full_node_protocol.RespondProofOfWeight.from_bytes(res.data).wp
        success, _, records = await wallet_node._weight_proof_handler.validate_weight_proof(weight_proof, True)
        weight_proof_short: WeightProof = full_node_protocol.RespondProofOfWeight.from_bytes(res_2.data).wp
        success, _, records_short = await wallet_node._weight_proof_handler.validate_weight_proof(
            weight_proof_short, True
        )
        weight_proof_long: WeightProof = full_node_protocol.RespondProofOfWeight.from_bytes(res_3.data).wp
        success, _, records_long = await wallet_node._weight_proof_handler.validate_weight_proof(
            weight_proof_long, True
        )

        async with DBConnection(1) as db_wrapper:
            store = await KeyValStore.create(db_wrapper)
            chain = await WalletBlockchain.create(store, test_constants)

            assert (await chain.get_peak_block()) is None
            assert chain.get_latest_timestamp() == 0

            await chain.new_valid_weight_proof(weight_proof, records)
            assert (await chain.get_peak_block()) is not None
            assert (await chain.get_peak_block()).height == 499
            assert chain.get_latest_timestamp() > 0

            await chain.new_valid_weight_proof(weight_proof_short, records_short)
            assert (await chain.get_peak_block()).height == 499

            await chain.new_valid_weight_proof(weight_proof_long, records_long)
            assert (await chain.get_peak_block()).height == 505

            header_blocks = []
            for block in default_1000_blocks:
                header_block = get_block_header(block, [], [])
                header_blocks.append(header_block)

            res, err = await chain.receive_block(header_blocks[50])
            print(res, err)
            assert res == ReceiveBlockResult.DISCONNECTED_BLOCK

            res, err = await chain.receive_block(header_blocks[400])
            print(res, err)
            assert res == ReceiveBlockResult.ALREADY_HAVE_BLOCK

            res, err = await chain.receive_block(header_blocks[507])
            print(res, err)
            assert res == ReceiveBlockResult.DISCONNECTED_BLOCK

            res, err = await chain.receive_block(
                dataclasses.replace(header_blocks[506], challenge_chain_ip_proof=VDFProof(2, b"123", True))
            )
            assert res == ReceiveBlockResult.INVALID_BLOCK

            assert (await chain.get_peak_block()).height == 505

            for block in header_blocks[506:]:
                res, err = await chain.receive_block(block)
                assert res == ReceiveBlockResult.NEW_PEAK
                assert (await chain.get_peak_block()).height == block.height

            assert (await chain.get_peak_block()).height == 999
